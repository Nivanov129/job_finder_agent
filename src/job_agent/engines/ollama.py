"""Ollama-движок: локальная модель через HTTP-API Ollama.

Полностью локально — данные не покидают машину. Реальный HTTP спрятан за
фасадом `HttpTransport`; в тестах подменяется фейком. Чистые функции
`build_request`/`parse_response` собирают запрос к `/api/chat` и достают текст.
У локальной модели web-поиска нет: при `web_search=True` флаг просто игнорируется.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import ConfigError
from .api_key import HttpTransport
from .base import Engine

if TYPE_CHECKING:
    from ..config import Config

__all__ = ["OllamaEngine", "build_request", "parse_response", "DEFAULT_BASE_URL"]

DEFAULT_BASE_URL = "http://localhost:11434"


def build_request(
    base_url: str, model: str, prompt: str
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Собрать (url, headers, body) для `/api/chat` Ollama (без стриминга)."""
    base = base_url.rstrip("/")
    headers = {"content-type": "application/json"}
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    return f"{base}/api/chat", headers, body


def parse_response(data: dict[str, Any]) -> str:
    """Достать текст ответа из JSON Ollama (`message.content`)."""
    return (data.get("message", {}).get("content") or "").strip()


def _httpx_transport(  # pragma: no cover - реальная сеть
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> dict[str, Any]:
    import httpx

    response = httpx.post(url, headers=headers, json=body, timeout=300.0)
    response.raise_for_status()
    return response.json()


class OllamaEngine(Engine):
    """Движок поверх локального Ollama."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        if not model:
            raise ConfigError("scoring_engine='ollama' требует непустого 'ollama_model'")
        self._model = model
        self._base_url = base_url or DEFAULT_BASE_URL
        self._transport = transport or _httpx_transport

    @classmethod
    def from_config(
        cls, config: Config, *, transport: HttpTransport | None = None
    ) -> OllamaEngine:
        if not config.ollama_model:
            raise ConfigError("scoring_engine='ollama' требует поля 'ollama_model'")
        return cls(
            config.ollama_model,
            base_url=config.api_base_url,
            transport=transport,
        )

    def complete(self, prompt: str, *, web_search: bool = False) -> str:
        del web_search  # локальная модель web-поиск не ведёт
        url, headers, body = build_request(self._base_url, self._model, prompt)
        data = self._transport(url, headers, body)
        return parse_response(data)
