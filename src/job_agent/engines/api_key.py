"""API-key движок: Anthropic / OpenAI через HTTP (httpx).

Реальный HTTP спрятан за фасадом `HttpTransport` (url, headers, body → JSON);
в тестах он подменяется фейком — юнит-тесты в сеть не ходят и не требуют httpx.
Чистые функции `build_request`/`parse_response` собирают запрос и достают текст —
их и тестируем. Секрет (`api_key`) живёт только в заголовках запроса; нигде не
логируется и не попадает в repr.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..config import ConfigError
from .base import Engine

if TYPE_CHECKING:
    from ..config import Config

__all__ = [
    "ApiKeyEngine",
    "HttpTransport",
    "build_request",
    "parse_response",
    "detect_provider",
    "KNOWN_PROVIDERS",
    "OPENROUTER_API_KEY_ENV",
]

KNOWN_PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "openrouter")

# Базовые URL БЕЗ хвоста /v1 — он добавляется в build_request (OpenAI-стиль).
_DEFAULT_BASE_URL = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
    "openrouter": "https://openrouter.ai/api",
}
_DEFAULT_MODEL = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-4o",
    # Мета-роутер OpenRouter: сам выбирает доступную бесплатную модель — выбор
    # модели в UI убран, всегда «что-то бесплатное и доступное».
    "openrouter": "openrouter/free",
}
# OpenAI-совместимые провайдеры: тело запроса и разбор ответа одинаковы.
_OPENAI_COMPATIBLE = ("openai", "openrouter")
#: Переменная окружения с ключом OpenRouter (секрет, живёт в `.env`).
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
_ANTHROPIC_VERSION = "2023-06-01"

# (url, headers, json_body) -> распарсенный JSON-ответ.
HttpTransport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def detect_provider(base_url: str | None) -> str:
    """Определить провайдера по base_url (по умолчанию Anthropic)."""
    if base_url and "openai" in base_url.lower():
        return "openai"
    return "anthropic"


def build_request(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    web_search: bool = False,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Собрать (url, headers, body) под выбранного провайдера.

    Для Anthropic при `web_search=True` подключается встроенный инструмент
    `web_search`; для OpenAI флаг принимается, но на тело не влияет.
    """
    base = base_url.rstrip("/")
    if provider == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if web_search:
            body["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]
        return f"{base}/v1/messages", headers, body
    if provider in _OPENAI_COMPATIBLE:
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        if provider == "openrouter":
            # Необязательные заголовки рейтинга OpenRouter (на работу не влияют).
            headers["x-title"] = "job-agent"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        return f"{base}/v1/chat/completions", headers, body
    known = ", ".join(KNOWN_PROVIDERS)
    raise ConfigError(f"неизвестный провайдер {provider!r}; ожидается один из: {known}")


def parse_response(provider: str, data: dict[str, Any]) -> str:
    """Достать текст ответа из JSON провайдера, склеив текстовые блоки."""
    if provider == "anthropic":
        blocks = data.get("content", []) or []
        parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        return "".join(parts).strip()
    if provider in _OPENAI_COMPATIBLE:
        choices = data.get("choices", []) or []
        if not choices:
            return ""
        return (choices[0].get("message", {}).get("content") or "").strip()
    known = ", ".join(KNOWN_PROVIDERS)
    raise ConfigError(f"неизвестный провайдер {provider!r}; ожидается один из: {known}")


def _httpx_transport(  # pragma: no cover - реальная сеть
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> dict[str, Any]:
    import httpx

    response = httpx.post(url, headers=headers, json=body, timeout=120.0)
    response.raise_for_status()
    return response.json()


class ApiKeyEngine(Engine):
    """Движок поверх HTTP-API Anthropic или OpenAI.

    `api_key` хранится приватно и в repr не раскрывается.
    """

    def __init__(
        self,
        api_key: str,
        *,
        provider: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        if not api_key:
            raise ConfigError("scoring_engine='api_key' требует непустого 'api_key'")
        self._provider = provider or detect_provider(base_url)
        if self._provider not in KNOWN_PROVIDERS:
            known = ", ".join(KNOWN_PROVIDERS)
            raise ConfigError(
                f"неизвестный провайдер {self._provider!r}; ожидается один из: {known}"
            )
        self._api_key = api_key
        self._base_url = base_url or _DEFAULT_BASE_URL[self._provider]
        self._model = model or _DEFAULT_MODEL[self._provider]
        self._transport = transport or _httpx_transport

    @classmethod
    def from_config(
        cls, config: Config, *, transport: HttpTransport | None = None
    ) -> ApiKeyEngine:
        if not config.api_key:
            raise ConfigError("scoring_engine='api_key' требует поля 'api_key'")
        return cls(
            config.api_key,
            base_url=config.api_base_url,
            transport=transport,
        )

    @classmethod
    def openrouter_from_env(
        cls, *, transport: HttpTransport | None = None
    ) -> ApiKeyEngine:
        """Движок OpenRouter: ключ из `.env` (OPENROUTER_API_KEY), базовый URL и
        бесплатная модель — по умолчанию (выбор модели в UI убран)."""
        import os

        key = os.environ.get(OPENROUTER_API_KEY_ENV, "")
        if not key:
            raise ConfigError(
                "scoring_engine='openrouter' требует ключ OPENROUTER_API_KEY "
                "(.env) — возьми бесплатный на openrouter.ai/keys"
            )
        return cls(key, provider="openrouter", transport=transport)

    @property
    def provider(self) -> str:
        return self._provider

    def __repr__(self) -> str:  # секрет не раскрываем
        return f"ApiKeyEngine(provider={self._provider!r}, model={self._model!r})"

    def complete(self, prompt: str, *, web_search: bool = False) -> str:
        url, headers, body = build_request(
            self._provider,
            self._base_url,
            self._api_key,
            self._model,
            prompt,
            web_search=web_search,
        )
        data = self._transport(url, headers, body)
        return parse_response(self._provider, data)
