"""SearXNG-провайдер web-поиска: self-host инстанс через JSON-API.

Полностью под контролем пользователя (self-host). Реальный HTTP спрятан за
фасадом `HttpGet` (url, params → JSON); в тестах подменяется фейком. Чистые
функции `build_request`/`parse_response` собирают запрос к `/search` и достают
результаты — их и тестируем.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..config import ConfigError
from .base import Searcher, SearchResult

if TYPE_CHECKING:
    from ..config import Config

__all__ = ["SearxngSearcher", "HttpGet", "build_request", "parse_response", "DEFAULT_BASE_URL"]

# Дефолтный адрес SearXNG — сервис из compose. Так web-поиск работает «из коробки»
# без ручной настройки; переопределяется env `JOB_AGENT_SEARXNG_URL` или конфигом.
DEFAULT_BASE_URL = "http://searxng:8080"

# (url, params) -> распарсенный JSON-ответ.
HttpGet = Callable[[str, dict[str, str]], dict[str, Any]]


def build_request(base_url: str, query: str) -> tuple[str, dict[str, str]]:
    """Собрать (url, params) для JSON-эндпоинта SearXNG `/search`."""
    base = base_url.rstrip("/")
    return f"{base}/search", {"q": query, "format": "json"}


def parse_response(data: dict[str, Any], *, max_results: int) -> list[SearchResult]:
    """Достать результаты из JSON SearXNG (`results[].title/url/content`)."""
    raw = data.get("results") or []
    out: list[SearchResult] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or ""
        title = item.get("title") or ""
        if not url and not title:
            continue
        out.append(
            SearchResult(
                title=title,
                url=url,
                snippet=item.get("content") or "",
            )
        )
        if len(out) >= max_results:
            break
    return out


def _httpx_get(  # pragma: no cover - реальная сеть
    url: str, params: dict[str, str]
) -> dict[str, Any]:
    import httpx

    response = httpx.get(url, params=params, timeout=30.0)
    response.raise_for_status()
    return response.json()


class SearxngSearcher(Searcher):
    """Web-поиск через self-host SearXNG."""

    def __init__(self, base_url: str, *, transport: HttpGet | None = None) -> None:
        if not base_url:
            raise ConfigError("web_search.provider='searxng' требует непустого 'url'")
        self._base_url = base_url
        self._transport = transport or _httpx_get

    @classmethod
    def from_config(cls, config: Config, *, transport: HttpGet | None = None) -> SearxngSearcher:
        # URL не обязателен: дефолт — сервис SearXNG из compose (env переопределяет),
        # чтобы web-поиск работал без ручной настройки.
        import os

        ws = config.web_search
        url = (
            (ws.url if ws else None)
            or os.environ.get("JOB_AGENT_SEARXNG_URL")
            or DEFAULT_BASE_URL
        )
        return cls(url, transport=transport)

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        url, params = build_request(self._base_url, query)
        data = self._transport(url, params)
        return parse_response(data, max_results=max_results)
