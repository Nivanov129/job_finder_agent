"""Коллектор публичных Telegram-каналов через web-превью `t.me/s/<handle>`.

Читает HTML-страницу превью канала, парсит виджеты сообщений (текст, ссылку на
пост, дату) и фильтрует по дате. Парсер на stdlib `html.parser` — без внешних
зависимостей. Сетевой доступ инкапсулирован в `HtmlFetcher`, который в тестах
подменяется фейком (юнит-тесты в сеть не ходят).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from html.parser import HTMLParser

from ..models import RawPost
from .base import Collector

__all__ = ["TelegramPublicCollector", "parse_tme_html", "HtmlFetcher"]

_logger = logging.getLogger("job_agent.collectors.telegram_public")

# url -> HTML страницы. Дефолт ходит в сеть; в тестах подменяется фейком.
HtmlFetcher = Callable[[str], str]


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


class _TmeParser(HTMLParser):
    """Извлекает сообщения со страницы `t.me/s/<handle>`.

    Каждое сообщение — блок `div.tgme_widget_message` с `data-post`. Текст берём
    из `div.tgme_widget_message_text`, дату — из `time[datetime]` внутри ссылки
    `a.tgme_widget_message_date`, ссылку — из её `href`.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[dict] = []
        self._cur: dict | None = None
        self._div_depth = 0
        self._in_text = False
        self._text_depth = 0
        self._in_date_link = False

    @staticmethod
    def _classes(attrs: dict[str, str | None]) -> str:
        return attrs.get("class") or ""

    def _flush(self) -> None:
        if self._cur is not None:
            self._cur["text"] = "".join(self._cur["text_parts"]).strip()
            del self._cur["text_parts"]
            self.messages.append(self._cur)
            self._cur = None

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        cls = self._classes(attrs)
        if tag == "div":
            self._div_depth += 1
            if "tgme_widget_message" in cls and attrs.get("data-post"):
                self._flush()
                self._cur = {
                    "data_post": attrs["data-post"],
                    "text_parts": [],
                    "url": None,
                    "datetime": None,
                }
            elif (
                self._cur is not None
                and not self._in_text
                and "tgme_widget_message_text" in cls
            ):
                self._in_text = True
                self._text_depth = self._div_depth
        elif tag == "br" and self._in_text:
            self._cur["text_parts"].append("\n")  # type: ignore[index]
        elif tag == "a" and self._cur is not None and "tgme_widget_message_date" in cls:
            self._in_date_link = True
            href = attrs.get("href")
            if href and not self._cur["url"]:
                self._cur["url"] = href
        elif tag == "time" and self._in_date_link and self._cur is not None:
            dt = attrs.get("datetime")
            if dt and not self._cur["datetime"]:
                self._cur["datetime"] = dt

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            if self._in_text and self._div_depth == self._text_depth:
                self._in_text = False
            self._div_depth -= 1
        elif tag == "a" and self._in_date_link:
            self._in_date_link = False

    def handle_data(self, data: str) -> None:
        if self._in_text and self._cur is not None:
            self._cur["text_parts"].append(data)

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


def parse_tme_html(html: str, handle: str) -> list[RawPost]:
    """Распарсить HTML страницы `t.me/s/<handle>` в список постов.

    Посты без текста (медиа-онли) отбрасываются. Ссылка берётся из виджета даты,
    иначе достраивается из `data-post`. Дата парсится из ISO-8601 (tz-aware).
    """
    parser = _TmeParser()
    parser.feed(html)
    parser.close()

    posts: list[RawPost] = []
    for msg in parser.messages:
        text = msg["text"]
        if not text:
            continue
        url = msg["url"] or f"https://t.me/{msg['data_post']}"
        date: datetime | None = None
        if msg["datetime"]:
            try:
                date = datetime.fromisoformat(msg["datetime"])
            except ValueError:
                date = None
        posts.append(
            RawPost(raw_text=text, source=f"tg:{handle}", url=url, date=date)
        )
    return posts


class TelegramPublicCollector(Collector):
    """Сбор постов из публичных каналов через `t.me/s/<handle>`."""

    def __init__(
        self,
        handles: Iterable[str],
        fetcher: HtmlFetcher | None = None,
    ) -> None:
        self._handles = [h.lstrip("@").strip() for h in handles if h.strip()]
        self._fetch_html: HtmlFetcher = fetcher or _http_fetch

    def fetch(self, since: datetime) -> list[RawPost]:
        since_aware = _as_aware(since)
        out: list[RawPost] = []
        for handle in self._handles:
            # Изоляция по каналу: недоступный канал/превью не валит остальные.
            try:
                html = self._fetch_html(f"https://t.me/s/{handle}")
            except Exception as exc:
                _logger.warning("канал %s пропущен: %s", handle, exc)
                continue
            for post in parse_tme_html(html, handle):
                if post.date is not None and _as_aware(post.date) < since_aware:
                    continue
                out.append(post)
        return out
