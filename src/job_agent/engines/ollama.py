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

from .api_key import HttpTransport
from .base import Engine

if TYPE_CHECKING:
    from ..config import Config

__all__ = [
    "OllamaEngine",
    "build_request",
    "v1_base",
    "parse_response",
    "explain_http_error",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "CLOUD_BASE_URL",
    "OLLAMA_API_KEY_ENV",
]

#: Облачный хост Ollama Cloud — дефолт (большие модели, авторизация по ключу).
CLOUD_BASE_URL = "https://ollama.com"
DEFAULT_BASE_URL = CLOUD_BASE_URL
#: Модель по умолчанию (выбор модели в UI убран): флагман Ollama Cloud,
#: бесплатный, многоязычный, хорош в строгом JSON.
DEFAULT_MODEL = "gpt-oss:120b"
#: Имя переменной окружения с ключом облака (живёт в `.env`, не в config.json).
OLLAMA_API_KEY_ENV = "OLLAMA_API_KEY"


def v1_base(base_url: str) -> str:
    """Базовый OpenAI-совместимый префикс `…/v1` (без дублирования /v1)."""
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def build_request(
    base_url: str, model: str, prompt: str, *, api_key: str | None = None
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Запрос к OpenAI-совместимому `/v1/chat/completions` Ollama (без стриминга).

    Ollama Cloud (`ollama.com`) и локальный сервер (`:11434`) оба поддерживают
    OpenAI-формат. При непустом `api_key` — заголовок `Authorization: Bearer`
    (облако). Имя модели — как в `/v1/models`, без суффикса `:cloud`.
    """
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    return f"{v1_base(base_url)}/chat/completions", headers, body


def parse_response(data: dict[str, Any]) -> str:
    """Достать текст из OpenAI-ответа (`choices[0].message.content`)."""
    choices = data.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message", {}).get("content") or "").strip()


def explain_http_error(status: int, model: str) -> str:
    """Понятное сообщение под коды Ollama Cloud (вместо сырого httpx-исключения)."""
    if status in (401, 403):
        return ("Ollama Cloud: ключ неверный/просрочен или нет доступа — возьми "
                "новый на ollama.com → Settings → Keys и вставь заново.")
    if status == 404:
        return (f"Ollama Cloud: модель «{model}» не найдена — выбери модель из "
                "списка «Загрузить модели».")
    if status == 429:
        return "Ollama Cloud: превышен лимит запросов — подожди и попробуй снова."
    return f"Ollama Cloud вернул HTTP {status}."


def _httpx_transport(  # pragma: no cover - реальная сеть
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> dict[str, Any]:
    import httpx

    response = httpx.post(url, headers=headers, json=body, timeout=300.0)
    if response.status_code >= 400:
        raise RuntimeError(
            explain_http_error(response.status_code, body.get("model", ""))
        )
    return response.json()


class OllamaEngine(Engine):
    """Движок поверх Ollama Cloud (или локального сервера Ollama)."""

    def __init__(
        self,
        model: str | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        # Выбор модели в UI убран — пустое значение даёт дефолт.
        self._model = model or DEFAULT_MODEL
        self._base_url = base_url or DEFAULT_BASE_URL
        self._api_key = api_key or None
        self._transport = transport or _httpx_transport

    @classmethod
    def from_config(
        cls, config: Config, *, transport: HttpTransport | None = None
    ) -> OllamaEngine:
        # Модель необязательна — при отсутствии берём DEFAULT_MODEL.
        return cls(
            config.ollama_model or None,
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
