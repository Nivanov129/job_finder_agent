"""Коллектор агрегатора vseti.app (HTML-листинг вакансий).

Парсит карточки вакансий со страницы листинга. Хрупкость вёрстки изолирована в
чистой функции `parse_vseti_html` — её и тестируем на фикстуре; сетевой доступ
инкапсулирован в `HtmlFetcher`, который в тестах подменяется фейком (юнит-тесты
в сеть не ходят). Поломка вёрстки vseti затрагивает только этот адаптер.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser

from ..models import RawPost
from .base import Collector

__all__ = ["VsetiCollector", "parse_vseti_html", "HtmlFetcher", "DEFAULT_URL"]

# url -> HTML страницы. Дефолт ходит в сеть; в тестах подменяется фейком.
HtmlFetcher = Callable[[str], str]

DEFAULT_URL = "https://vseti.app/jobs"
_BASE = "https://vseti.app"


def _http_fetch(url: str) -> str:  # pragma: no cover - реальная сеть, не в юнит-тестах
    import httpx

    resp = httpx.get(
        url,
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (job-agent)"},
    )
    resp.raise_for_status()
    return resp.text


def _as_aware(dt: datetime) -> datetime:
    """Привести datetime к tz-aware (наивный считаем UTC) для сравнения."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# Поля карточки и классы их контейнеров. Текст внутри контейнера накапливается,
# пока активен соответствующий `div`/`a` (по глубине вложенности).
_FIELD_CLASSES = {
    "title": "vacancy-card__title",
    "company": "vacancy-card__company",
    "salary": "vacancy-card__salary",
    "description": "vacancy-card__description",
}


class _VsetiParser(HTMLParser):
    """Извлекает карточки `div.vacancy-card` со страницы листинга vseti.app.

    Заголовок — ссылка `a.vacancy-card__title` (даёт текст и `href`), остальные
    поля — текст одноимённых контейнеров, дата — `time[datetime]` внутри карточки.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._cur: dict | None = None
        self._depth = 0
        # имя поля, которое сейчас собираем, и глубина его открывающего тега
        self._field: str | None = None
        self._field_depth = 0

    @staticmethod
    def _classes(attrs: dict[str, str | None]) -> set[str]:
        return set((attrs.get("class") or "").split())

    def _flush(self) -> None:
        if self._cur is not None:
            for key in ("title", "company", "salary", "description"):
                self._cur[key] = "".join(self._cur[f"{key}_parts"]).strip()
                del self._cur[f"{key}_parts"]
            self.cards.append(self._cur)
            self._cur = None
            self._field = None

    def _start_field(self, name: str) -> None:
        if self._cur is not None and self._field is None:
            self._field = name
            self._field_depth = self._depth

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        cls = self._classes(attrs)
        if tag == "div":
            self._depth += 1
            if "vacancy-card" in cls:
                self._flush()
                self._cur = {
                    "title_parts": [],
                    "company_parts": [],
                    "salary_parts": [],
                    "description_parts": [],
                    "url": None,
                    "datetime": None,
                }
            else:
                for name, klass in _FIELD_CLASSES.items():
                    if name != "title" and klass in cls:
                        self._start_field(name)
                        break
        elif tag == "a" and self._cur is not None and "vacancy-card__title" in cls:
            self._depth += 1
            href = attrs.get("href")
            if href and not self._cur["url"]:
                self._cur["url"] = href if href.startswith("http") else f"{_BASE}{href}"
            self._start_field("title")
        elif tag == "time" and self._cur is not None:
            dt = attrs.get("datetime")
            if dt and not self._cur["datetime"]:
                self._cur["datetime"] = dt
        elif tag == "br" and self._field is not None and self._cur is not None:
            self._cur[f"{self._field}_parts"].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("div", "a"):
            if self._field is not None and self._depth == self._field_depth:
                self._field = None
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._field is not None and self._cur is not None:
            self._cur[f"{self._field}_parts"].append(data)

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


def parse_vseti_html(html: str) -> list[RawPost]:
    """Распарсить страницу листинга vseti.app в список постов.

    Карточки без заголовка отбрасываются. `raw_text` собирается из полей карточки
    (заголовок · компания · зарплата · описание) — материал для стадии нормализации.
    Дата парсится из ISO-8601 (tz-aware), отсутствие/мусор → `None`.
    """
    parser = _VsetiParser()
    parser.feed(html)
    parser.close()

    posts: list[RawPost] = []
    for card in parser.cards:
        title = card["title"]
        if not title:
            continue
        lines = [title]
        for key in ("company", "salary", "description"):
            if card[key]:
                lines.append(card[key])
        raw_text = "\n".join(lines)

        date: datetime | None = None
        if card["datetime"]:
            try:
                date = datetime.fromisoformat(card["datetime"])
            except ValueError:
                date = None

        posts.append(
            RawPost(raw_text=raw_text, source="vseti", url=card["url"], date=date)
        )
    return posts


class VsetiCollector(Collector):
    """Сбор вакансий с листинга vseti.app."""

    def __init__(self, url: str = DEFAULT_URL, fetcher: HtmlFetcher | None = None) -> None:
        self._url = url
        self._fetch_html: HtmlFetcher = fetcher or _http_fetch

    def fetch(self, since: datetime) -> list[RawPost]:
        since_aware = _as_aware(since)
        html = self._fetch_html(self._url)
        out: list[RawPost] = []
        for post in parse_vseti_html(html):
            if post.date is not None and _as_aware(post.date) < since_aware:
                continue
            out.append(post)
        return out
