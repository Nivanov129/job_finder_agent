"""Детекция состояния AI-движков для страницы «AI · авторизация».

Для каждого движка отвечаем на два вопроса: установлен ли инструмент и есть ли
авторизация — чтобы UI показал статус и подсказал установку/вход, если чего-то
не хватает. Внешние границы (поиск бинаря, версия, наличие creds-файла,
окружение, HTTP к Ollama) инъектируются — юнит-тесты в сеть/процессы не ходят.
Секреты не возвращаются: только факт наличия (bool).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "EngineStatus",
    "engine_statuses",
    "claude_status",
    "codex_status",
    "ollama_status",
    "ollama_models",
    "openrouter_status",
    "recommend_first",
    "CLOUD_BASE_URL",
    "OPENROUTER_BASE_URL",
]

# Внешние границы (в тестах подменяются фейками).
WhichFn = Callable[[str], str | None]
RunFn = Callable[[list[str]], str]  # argv -> stdout (для --version)
# (url, headers) -> json (Ollama /api/tags; headers несут Bearer для облака).
HttpGetFn = Callable[[str, Mapping[str, str]], dict[str, Any]]

# Куда CLI-агенты кладут авторизацию (внутри контейнера; см. mounts в compose).
CLAUDE_CREDS = Path("/root/.claude/.credentials.json")
CODEX_AUTH = Path("/root/.codex/auth.json")
# Облачный хост Ollama Cloud — дефолт, если адрес своего сервера не задан.
CLOUD_BASE_URL = "https://ollama.com"
# OpenAI-совместимый эндпоинт OpenRouter.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class EngineStatus:
    """Состояние одного движка для рендера карточки на странице авторизации."""

    key: str  # claude | codex | ollama
    label: str
    billing: str  # subscription | free
    installed: bool | None  # None — неприменимо (ollama не CLI)
    authorized: bool | None  # None — неизвестно (нельзя проверить дёшево)
    detail: str  # короткая подсказка/версия (без секретов)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_version(run: RunFn, tool: str) -> str:
    try:
        return run([tool, "--version"]).strip().splitlines()[0]
    except Exception:  # pragma: no cover - зависит от среды
        return ""


def claude_status(
    *, which: WhichFn, run: RunFn, env: Mapping[str, str], creds_path: Path = CLAUDE_CREDS
) -> EngineStatus:
    installed = which("claude") is not None
    has_token = bool(env.get("CLAUDE_CODE_OAUTH_TOKEN") or env.get("ANTHROPIC_API_KEY"))
    authorized = installed and (creds_path.exists() or has_token)
    if not installed:
        detail = "claude не установлен в образе"
    elif authorized:
        detail = _safe_version(run, "claude") or "готов"
    else:
        detail = "нужен вход: `claude setup-token` → вставьте токен ниже"
    return EngineStatus("claude", "Claude Code", "subscription", installed, authorized, detail)


def codex_status(
    *, which: WhichFn, run: RunFn, env: Mapping[str, str], auth_path: Path = CODEX_AUTH
) -> EngineStatus:
    installed = which("codex") is not None
    has_key = bool(env.get("OPENAI_API_KEY"))
    authorized = installed and (auth_path.exists() or has_key)
    if not installed:
        detail = "codex не установлен в образе"
    elif authorized:
        detail = _safe_version(run, "codex") or "готов"
    else:
        detail = "нужен вход: `codex login` или ключ OPENAI_API_KEY ниже"
    return EngineStatus("codex", "Codex", "subscription", installed, authorized, detail)


def _ollama_headers(api_key: str | None) -> dict[str, str]:
    return {"authorization": f"Bearer {api_key}"} if api_key else {}


def ollama_models(
    url: str = "", *, api_key: str | None = None, http_get: HttpGetFn | None = None
) -> list[str]:
    """Список моделей Ollama через OpenAI-совместимый `/v1/models`.

    Возвращает id моделей (как есть, без суффикса `:cloud`). Облако и свой сервер
    оба отдают OpenAI-формат `{data:[{id}]}`. Сетевые ошибки → пустой список.
    """
    from job_agent.engines.ollama import v1_base

    http_get = http_get or _default_http_get
    base = url or CLOUD_BASE_URL
    try:
        data = http_get(f"{v1_base(base)}/models", _ollama_headers(api_key))
    except Exception:
        return []
    return [m.get("id", "") for m in (data.get("data") or []) if m.get("id")]


# Семейства моделей, хорошо подходящих под нашу задачу (скоринг: рассуждение,
# многоязычность вкл. русский, строгий JSON). Имена не выдумываем — фильтруем
# реальный список с сервера, поднимая подходящие наверх.
RECOMMENDED_FAMILIES: tuple[str, ...] = (
    "gpt-oss", "deepseek", "qwen3", "qwen2.5", "glm", "kimi", "llama3", "llama4",
    "mistral", "gemma", "command",
)


def recommend_first(models: list[str]) -> list[str]:
    """Поднять подходящие под задачу модели наверх (порядок семейств — приоритет).

    Возвращает рекомендованные (в порядке `RECOMMENDED_FAMILIES`) + остальные.
    """
    def rank(name: str) -> int:
        low = name.lower()
        for i, fam in enumerate(RECOMMENDED_FAMILIES):
            if fam in low:
                return i
        return len(RECOMMENDED_FAMILIES)

    return sorted(models, key=lambda m: (rank(m), m))


def ollama_status(
    url: str = "", *, api_key: str | None = None, http_get: HttpGetFn
) -> EngineStatus:
    base = (url or CLOUD_BASE_URL).rstrip("/")
    is_cloud = base == CLOUD_BASE_URL or bool(api_key)
    label = "Ollama Cloud" if is_cloud else "Ollama"
    # Облаку нужен ключ — без него и не пытаемся ходить в сеть.
    if is_cloud and not api_key:
        return EngineStatus(
            "ollama", label, "free", None, False,
            "нужен ключ OLLAMA_API_KEY (ollama.com/settings/keys)",
        )
    from job_agent.engines.ollama import v1_base

    try:
        data = http_get(f"{v1_base(base)}/models", _ollama_headers(api_key))
        models = [m.get("id", "") for m in (data.get("data") or [])]
        n = len(list(filter(None, models)))
        if is_cloud:
            # /v1/models у ollama.com ПУБЛИЧНЫЙ — не проверяет ключ. Поэтому статус
            # «авторизован» тут лгал бы. Честно: ключ задан, но не проверен —
            # реальная проверка кнопкой «Проверить» (минимальный chat-запрос).
            detail = f"ключ задан · моделей: {n} · проверь кнопкой «Проверить»"
            return EngineStatus("ollama", label, "free", None, None, detail)
        detail = ("модели: " + ", ".join(filter(None, models))) if models else "сервер доступен"
        return EngineStatus("ollama", label, "free", None, True, detail)
    except Exception:
        where = "облако ollama.com" if is_cloud else url
        return EngineStatus("ollama", label, "free", None, False, f"недоступно: {where}")


def openrouter_status(
    *, api_key: str | None, http_get: HttpGetFn
) -> EngineStatus:
    """Состояние OpenRouter: проверяем ключ дёшево через `/v1/key` (требует
    авторизации — даёт честный authorized=True/False), модель — бесплатная по
    умолчанию, выбор модели в UI нет."""
    label = "OpenRouter"
    if not api_key:
        return EngineStatus(
            "openrouter", label, "free", None, False,
            "нужен ключ OPENROUTER_API_KEY (openrouter.ai/keys, бесплатно)",
        )
    try:
        http_get(
            f"{OPENROUTER_BASE_URL}/key", {"authorization": f"Bearer {api_key}"}
        )
        return EngineStatus(
            "openrouter", label, "free", None, True,
            "ключ принят · бесплатная модель по умолчанию (openrouter/free)",
        )
    except Exception:
        return EngineStatus(
            "openrouter", label, "free", None, False,
            "ключ неверный или сеть недоступна",
        )


def engine_statuses(
    *,
    env: Mapping[str, str],
    ollama_url: str = "",
    which: WhichFn = shutil.which,
    run: RunFn | None = None,
    http_get: HttpGetFn | None = None,
) -> list[EngineStatus]:
    """Состояния всех движков (порядок = порядок карточек в UI).

    Ключи берутся из `.env`: Ollama Cloud — `OLLAMA_API_KEY`, OpenRouter —
    `OPENROUTER_API_KEY` (секреты живут в `.env`).
    """
    run = run or _default_run
    http_get = http_get or _default_http_get
    return [
        codex_status(which=which, run=run, env=env),
        ollama_status(ollama_url, api_key=env.get("OLLAMA_API_KEY"), http_get=http_get),
        openrouter_status(api_key=env.get("OPENROUTER_API_KEY"), http_get=http_get),
    ]


def _default_run(argv: list[str]) -> str:  # pragma: no cover - реальный процесс
    import subprocess

    return subprocess.run(argv, capture_output=True, text=True, timeout=10).stdout


def _default_http_get(  # pragma: no cover - реальная сеть
    url: str, headers: Mapping[str, str]
) -> dict[str, Any]:
    import httpx

    r = httpx.get(url, headers=dict(headers), timeout=5.0)
    r.raise_for_status()
    return r.json()
