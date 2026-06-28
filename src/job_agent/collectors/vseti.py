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


# vseti.app — Webflow CMS: каждая вакансия — ссылка `a.card-jobs` на `/vakansii/<id>`,
# внутри весь текст карточки (должность, компания, зарплата, формат, теги). Берём
# href как url и весь текст карточки как `raw_text` — нормализация вытащит поля.
_CARD_CLASS = "card-jobs"
# Блочные теги — на границах вставляем перенос, чтобы текст не слипался.
_BLOCK_TAGS = {"div", "p", "h1", "h2", "h3", "h4", "li", "br", "span"}
# Void-элементы (без закрывающего тега) — не считаем во вложенность, иначе
# глубина «уплывает» и закрытие карточки `</a>` не ловится.
_VOID_TAGS = {
    "br", "img", "input", "hr", "meta", "link", "source", "wbr", "col",
    "area", "base", "embed", "track", "param",
}


class _VsetiParser(HTMLParser):
    """Извлекает карточки-ссылки `a.card-jobs` со страницы листинга vseti.app."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._cur: dict | None = None
        self._depth = 0  # вложенность тегов внутри активной карточки-ссылки

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        cls = attrs.get("class") or ""
        if tag == "a" and _CARD_CLASS in cls and self._cur is None:
            href = (attrs.get("href") or "").strip()
            if href and not href.startswith("http"):
                href = f"{_BASE}{href}"
            self._cur = {"url": href, "parts": []}
            self._depth = 0
            return
        if self._cur is not None:
            if tag not in _VOID_TAGS:
                self._depth += 1
            if tag in _BLOCK_TAGS:
                self._cur["parts"].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._cur is None:
            return
        if tag == "a" and self._depth == 0:
            self._flush()
        elif tag not in _VOID_TAGS and self._depth > 0:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._cur is not None:
            self._cur["parts"].append(data)

    def _flush(self) -> None:
        if self._cur is not None:
            text = " ".join("".join(self._cur["parts"]).split())
            self.cards.append({"url": self._cur["url"], "text": text})
            self._cur = None

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


def parse_vseti_html(html: str) -> list[RawPost]:
    """Распарсить листинг vseti.app в список постов.

    Каждая карточка-ссылка `a.card-jobs` → один `RawPost`: весь текст карточки как
    `raw_text` (материал для нормализации), href как url. Дата не указана в карточке
    (листинг свежий) → `None`, т.е. пост не отсекается по `since`. Пустые карточки
    пропускаются.
    """
    parser = _VsetiParser()
    parser.feed(html)
    parser.close()

    posts: list[RawPost] = []
    for card in parser.cards:
        text = card["text"]
        if len(text) < 5 or not card["url"]:
            continue
        posts.append(RawPost(raw_text=text, source="vseti", url=card["url"], date=None))
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
