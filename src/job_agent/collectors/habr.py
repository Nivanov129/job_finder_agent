"""Коллектор агрегатора career.habr.com (HTML-листинг вакансий).

Парсит карточки `div.vacancy-card` со страницы листинга: ссылку (`/vacancies/<id>`),
дату (`time[datetime]`, ISO) и весь текст карточки как `raw_text` (материал для
нормализации). Хрупкость вёрстки изолирована в чистой `parse_habr_html` — её и
тестируем на фикстуре; сеть — за `HtmlFetcher` (в тестах фейк). Поломка вёрстки
затрагивает только этот адаптер.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser

from ..models import RawPost
from .base import Collector

__all__ = ["HabrCollector", "parse_habr_html", "HtmlFetcher", "DEFAULT_URL"]

HtmlFetcher = Callable[[str], str]

DEFAULT_URL = "https://career.habr.com/vacancies?sort=date&type=all"
_BASE = "https://career.habr.com"

_BLOCK_TAGS = {"div", "p", "h1", "h2", "h3", "h4", "li", "br", "span", "time"}
_VOID_TAGS = {
    "br", "img", "input", "hr", "meta", "link", "source", "wbr", "col",
    "area", "base", "embed", "track", "param", "use",
}


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
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class _HabrParser(HTMLParser):
    """Извлекает карточки `div.vacancy-card` со страницы career.habr.com."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._cur: dict | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        classes = (attrs.get("class") or "").split()
        # Внешний контейнер карточки — ровно класс "vacancy-card" (не __inner и т.п.).
        if tag == "div" and "vacancy-card" in classes:
            self._flush()  # подстраховка: закрыть предыдущую, если вёрстка «уплыла»
            self._cur = {"url": None, "date": None, "parts": []}
            self._depth = 0
            return
        if self._cur is None:
            return
        href = attrs.get("href") or ""
        if "/vacancies/" in href and not self._cur["url"]:
            self._cur["url"] = href if href.startswith("http") else f"{_BASE}{href}"
        if tag == "time" and attrs.get("datetime") and not self._cur["date"]:
            self._cur["date"] = attrs["datetime"]
        if tag not in _VOID_TAGS:
            self._depth += 1
        if tag in _BLOCK_TAGS:
            self._cur["parts"].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._cur is None:
            return
        if tag == "div" and self._depth == 0:
            self._flush()
        elif tag not in _VOID_TAGS and self._depth > 0:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._cur is not None:
            self._cur["parts"].append(data)

    def _flush(self) -> None:
        if self._cur is not None:
            text = " ".join("".join(self._cur["parts"]).split())
            self.cards.append(
                {"url": self._cur["url"], "date": self._cur["date"], "text": text}
            )
            self._cur = None

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


def parse_habr_html(html: str) -> list[RawPost]:
    """Распарсить листинг career.habr.com в список постов.

    Каждая `div.vacancy-card` → один `RawPost`: весь текст карточки как `raw_text`,
    ссылка `/vacancies/<id>`, дата из `time[datetime]` (ISO, tz-aware). Карточки без
    ссылки или текста пропускаются.
    """
    parser = _HabrParser()
    parser.feed(html)
    parser.close()

    posts: list[RawPost] = []
    for card in parser.cards:
        text = card["text"]
        if len(text) < 5 or not card["url"]:
            continue
        date: datetime | None = None
        if card["date"]:
            try:
                date = datetime.fromisoformat(card["date"])
            except ValueError:
                date = None
        posts.append(
            RawPost(raw_text=text, source="habr", url=card["url"], date=date)
        )
    return posts


class HabrCollector(Collector):
    """Сбор вакансий с листинга career.habr.com."""

    def __init__(self, url: str = DEFAULT_URL, fetcher: HtmlFetcher | None = None) -> None:
        self._url = url
        self._fetch_html: HtmlFetcher = fetcher or _http_fetch

    def fetch(self, since: datetime) -> list[RawPost]:
        since_aware = _as_aware(since)
        html = self._fetch_html(self._url)
        out: list[RawPost] = []
        for post in parse_habr_html(html):
            if post.date is not None and _as_aware(post.date) < since_aware:
                continue
            out.append(post)
        return out
