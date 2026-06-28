"""SERP-провайдер web-поиска: облачный SERP-API по ключу.

Реальный HTTP спрятан за фасадом `HttpGet`; в тестах подменяется фейком. Чистые
функции `build_request`/`parse_response` собирают запрос и достают результаты.
Секрет (`api_key`) живёт только в параметрах запроса; нигде не логируется и не
попадает в repr.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import ConfigError
from .base import Searcher, SearchResult
from .searxng import HttpGet

if TYPE_CHECKING:
    from ..config import Config

__all__ = ["SerpSearcher", "build_request", "parse_response", "DEFAULT_BASE_URL"]

DEFAULT_BASE_URL = "https://serpapi.com"


def build_request(base_url: str, api_key: str, query: str) -> tuple[str, dict[str, str]]:
    """Собрать (url, params) для SERP-API (Google engine)."""
    base = base_url.rstrip("/")
    return f"{base}/search", {"q": query, "engine": "google", "api_key": api_key}


def parse_response(data: dict[str, Any], *, max_results: int) -> list[SearchResult]:
    """Достать результаты из JSON SERP (`organic_results[].title/link/snippet`)."""
    raw = data.get("organic_results") or []
    out: list[SearchResult] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = item.get("link") or ""
        title = item.get("title") or ""
        if not url and not title:
            continue
        out.append(
            SearchResult(
                title=title,
                url=url,
                snippet=item.get("snippet") or "",
            )
        )
        if len(out) >= max_results:
            break
    return out


class SerpSearcher(Searcher):
    """Web-поиск через облачный SERP-провайдер по ключу.

    `api_key` хранится приватно и в repr не раскрывается.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        transport: HttpGet | None = None,
    ) -> None:
        if not api_key:
            raise ConfigError("web_search.provider='serp' требует непустого 'api_key'")
        self._api_key = api_key
        self._base_url = base_url or DEFAULT_BASE_URL
        # Импорт фасада из searxng оставляет одну точку реальной сети.
        from .searxng import _httpx_get

        self._transport = transport or _httpx_get

    @classmethod
    def from_config(cls, config: Config, *, transport: HttpGet | None = None) -> SerpSearcher:
        ws = config.web_search
        if ws is None or not ws.api_key:
            raise ConfigError("web_search.provider='serp' требует поля 'web_search.api_key'")
        return cls(ws.api_key, base_url=ws.url, transport=transport)

    def __repr__(self) -> str:  # секрет не раскрываем
        return f"SerpSearcher(base_url={self._base_url!r})"

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        url, params = build_request(self._base_url, self._api_key, query)
        data = self._transport(url, params)
        return parse_response(data, max_results=max_results)
