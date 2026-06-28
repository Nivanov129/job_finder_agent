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
    "CLOUD_BASE_URL",
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


@dataclass
class EngineStatus:
    """Состояние одного движка для рендера карточки на странице авторизации."""

    key: str  # claude | codex | ollama | api_key
    label: str
    billing: str  # subscription | free | byo_key
    installed: bool | None  # None — неприменимо (api_key/ollama не CLI)
    authorized: bool
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
    """Список доступных моделей Ollama (облако или свой сервер) через `/api/tags`.

    Облако (`ollama.com`) требует ключ — заголовок `Authorization: Bearer`.
    Сетевые ошибки наружу не пробрасываются: недоступность → пустой список.
    """
    http_get = http_get or _default_http_get
    base = (url or CLOUD_BASE_URL).rstrip("/")
    try:
        data = http_get(f"{base}/api/tags", _ollama_headers(api_key))
    except Exception:
        return []
    return [m.get("name", "") for m in (data.get("models") or []) if m.get("name")]


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
    try:
        data = http_get(f"{base}/api/tags", _ollama_headers(api_key))
        models = [m.get("name", "") for m in (data.get("models") or [])]
        detail = ("модели: " + ", ".join(filter(None, models))) if models else "сервер доступен"
        return EngineStatus("ollama", label, "free", None, True, detail)
    except Exception:
        where = "облако ollama.com" if is_cloud else url
        return EngineStatus("ollama", label, "free", None, False, f"недоступно: {where}")


def api_key_status(*, has_key: bool) -> EngineStatus:
    detail = "ключ задан" if has_key else "вставьте API-ключ ниже"
    return EngineStatus("api_key", "Свой API-ключ", "byo_key", None, has_key, detail)


def engine_statuses(
    *,
    env: Mapping[str, str],
    ollama_url: str = "",
    has_api_key: bool = False,
    which: WhichFn = shutil.which,
    run: RunFn | None = None,
    http_get: HttpGetFn | None = None,
) -> list[EngineStatus]:
    """Состояния всех движков (порядок = порядок карточек в UI).

    Ключ Ollama Cloud берётся из `env['OLLAMA_API_KEY']` — секрет живёт в `.env`.
    """
    run = run or _default_run
    http_get = http_get or _default_http_get
    return [
        claude_status(which=which, run=run, env=env),
        codex_status(which=which, run=run, env=env),
        ollama_status(ollama_url, api_key=env.get("OLLAMA_API_KEY"), http_get=http_get),
        api_key_status(has_key=has_api_key),
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
