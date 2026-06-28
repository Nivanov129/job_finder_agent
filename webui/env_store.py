"""Чтение/запись `/data/.env`: токены авторизации AI-движков и прочие секреты.

Секреты не живут в `config.json` (его легко расшарить): CLI-агенты читают
`CLAUDE_CODE_OAUTH_TOKEN` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` из окружения,
а его наполняет этот `.env` (его подхватывает compose через `env_file`). Запись
атомарная (temp+replace) и мержит существующие ключи — чужие переменные (Telethon,
токен бота) не затираются. Значения секретов нигде не логируются.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

__all__ = ["parse_env", "merge_env", "KNOWN_AUTH_KEYS"]

#: Ключи авторизации AI-движков, которыми управляет страница «AI · авторизация».
KNOWN_AUTH_KEYS: tuple[str, ...] = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OLLAMA_API_KEY",
)


def parse_env(path: str | Path) -> dict[str, str]:
    """Разобрать `.env` в dict (KEY=VALUE построчно).

    Пустые строки и комментарии (`#`) игнорируются; снимаются обрамляющие
    кавычки. Несуществующий файл → пустой dict.
    """
    p = Path(path)
    if not p.exists():
        return {}
    values: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key:
            values[key] = val
    return values


def merge_env(path: str | Path, updates: Mapping[str, str | None]) -> Path:
    """Слить `updates` в `.env` и атомарно записать.

    `None`/`""` значение удаляет ключ; прочие — задают/обновляют. Остальные
    переменные файла сохраняются. Возвращает путь записанного файла.
    """
    p = Path(path)
    values = parse_env(p)
    for key, val in updates.items():
        if val:
            values[key] = val
        else:
            values.pop(key, None)

    p.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{k}={v}\n" for k, v in values.items())
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(p)
    return p
