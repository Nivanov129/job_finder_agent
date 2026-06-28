"""Ollama-движок: облачные модели Ollama Cloud (или локальный сервер) через HTTP.

Облако (`https://ollama.com`) — дефолт: даёт большие модели без локального GPU,
авторизация по ключу `OLLAMA_API_KEY` (заголовок `Authorization: Bearer`). Тот же
адаптер работает с локальным/self-host сервером — достаточно задать `api_base_url`
(напр. `http://host.docker.internal:11434`); без ключа заголовок авторизации не
шлётся. Данные уходят только к выбранному пользователем движку (облачному или
своему) — это и есть «выбранный AI-движок» из инвариантов.

Реальный HTTP спрятан за фасадом `HttpTransport`; в тестах подменяется фейком.
Чистые функции `build_request`/`parse_response` собирают запрос к `/api/chat` и
достают текст. У Ollama своего web-поиска нет: при `web_search=True` флаг игнорится.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from ..config import ConfigError
from .api_key import HttpTransport
from .base import Engine

if TYPE_CHECKING:
    from ..config import Config

__all__ = [
    "OllamaEngine",
    "build_request",
    "parse_response",
    "DEFAULT_BASE_URL",
    "CLOUD_BASE_URL",
    "OLLAMA_API_KEY_ENV",
]

#: Облачный хост Ollama Cloud — дефолт (большие модели, авторизация по ключу).
CLOUD_BASE_URL = "https://ollama.com"
DEFAULT_BASE_URL = CLOUD_BASE_URL
#: Имя переменной окружения с ключом облака (живёт в `.env`, не в config.json).
OLLAMA_API_KEY_ENV = "OLLAMA_API_KEY"


def build_request(
    base_url: str, model: str, prompt: str, *, api_key: str | None = None
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Собрать (url, headers, body) для `/api/chat` Ollama (без стриминга).

    При непустом `api_key` добавляется заголовок `Authorization: Bearer <key>`
    (Ollama Cloud); для локального сервера ключ не нужен — заголовок опускается.
    """
    base = base_url.rstrip("/")
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
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
    """Движок поверх Ollama Cloud (или локального сервера Ollama)."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        if not model:
            raise ConfigError("scoring_engine='ollama' требует непустого 'ollama_model'")
        self._model = model
        self._base_url = base_url or DEFAULT_BASE_URL
        self._api_key = api_key or None
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
            # Ключ облака — секрет, живёт в окружении (`.env`), не в config.json.
            api_key=os.environ.get(OLLAMA_API_KEY_ENV),
            transport=transport,
        )

    def __repr__(self) -> str:  # ключ облака не раскрываем
        return f"OllamaEngine(model={self._model!r}, base_url={self._base_url!r})"

    def complete(self, prompt: str, *, web_search: bool = False) -> str:
        del web_search  # у Ollama своего web-поиска нет
        url, headers, body = build_request(
            self._base_url, self._model, prompt, api_key=self._api_key
        )
        data = self._transport(url, headers, body)
        return parse_response(data)
