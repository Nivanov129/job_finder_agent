"""Преобразование данных формы «Настройка» (Экран 1) в конфиг участника.

Чистая логика без HTTP: на входе — multimap формы (объект с `.get`/`.getlist`,
такой как `starlette.datastructures.FormData`), на выходе — dict, валидный по
`config.schema.json`. Маршрут (`app.py`) валидирует результат через
`job_agent.config.load_config` и пишет `config.json`.

Модель направлений динамическая: поля трека (`track_name`, `track_resume`, …)
приходят повторяющимися списками — пары собираются по индексу. Минимум один трек.
"""

from __future__ import annotations

import re
from typing import Any, Protocol


class FormLike(Protocol):
    """Минимальный интерфейс multimap формы (FormData/наш фейк в тестах)."""

    def get(self, key: str, default: str = ...) -> Any: ...
    def getlist(self, key: str) -> list[Any]: ...


_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_SPLIT_RE = re.compile(r"[\n,]+")


def slugify(name: str, *, index: int) -> str:
    """Машинный `id` трека из имени (паттерн `^[a-z0-9_-]+$`).

    Кириллица/пустое имя дают пустой слаг → фолбэк `track-<n>` (тоже валиден).
    """
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or f"track-{index + 1}"


def _split(raw: str) -> list[str]:
    """Разбить строку по запятым/переводам строк, выкинуть пустое."""
    return [item.strip() for item in _SPLIT_RE.split(raw or "") if item.strip()]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _tracks_from_form(form: FormLike) -> list[dict[str, Any]]:
    """Собрать `tracks[]` из повторяющихся полей формы (пары по индексу)."""
    names = [_clean(v) for v in form.getlist("track_name")]
    resumes = [_clean(v) for v in form.getlist("track_resume")]
    templates = [_clean(v) for v in form.getlist("track_template")]
    roles = [_clean(v) for v in form.getlist("track_roles")]

    tracks: list[dict[str, Any]] = []
    for i, name in enumerate(names):
        resume = resumes[i] if i < len(resumes) else ""
        # Пропускаем полностью пустые карточки (артефакт клонирования в UI).
        if not name and not resume:
            continue
        track: dict[str, Any] = {
            "id": slugify(name, index=len(tracks)),
            "name": name,
            "resume_path": resume,
        }
        if i < len(templates) and templates[i]:
            track["cover_template_path"] = templates[i]
        if i < len(roles) and roles[i]:
            track["role_gate"] = _split(roles[i])
        tracks.append(track)
    return tracks


def _channels_from_form(form: FormLike) -> list[dict[str, Any]]:
    """Каналы из textarea (по строке на канал, ведущий `@` снимается)."""
    raw = _clean(form.get("channels", ""))
    channels: list[dict[str, Any]] = []
    for line in raw.splitlines():
        handle = line.strip().lstrip("@").strip()
        if handle:
            channels.append({"handle": handle, "private": False})
    return channels


def _output_mode(form: FormLike) -> str:
    table = bool(form.get("out_table"))
    bot = bool(form.get("out_bot"))
    if table and bot:
        return "both"
    if bot:
        return "bot"
    return "table"


def config_from_form(form: FormLike) -> dict[str, Any]:
    """Построить dict-конфиг из данных формы (валидность проверяет вызывающий).

    Опциональные пустые поля опускаются — конфиг остаётся компактным и валидным.
    """
    data: dict[str, Any] = {
        "version": 1,
        "tracks": _tracks_from_form(form),
        "output_mode": _output_mode(form),
    }

    # Карта поиска — общий файл-якорь.
    search_map_path = _clean(form.get("search_map_path", ""))
    if search_map_path:
        data["search_map"] = {"path": search_map_path}

    # Глобальный гейт ролей / дисквалификаторы.
    global_roles = _split(_clean(form.get("global_role_gate", "")))
    if global_roles:
        data["global_role_gate"] = global_roles
    global_disq = _clean(form.get("global_disqualifiers", ""))
    if global_disq:
        data["global_disqualifiers"] = global_disq

    # Источники.
    channels = _channels_from_form(form)
    if channels:
        data["tg_channels"] = channels
    data["use_aggregators"] = bool(form.get("use_aggregators"))

    # Движок AI и web-поиск — на отдельной странице (engine_config_from_form),
    # сюда не входят: сохранение Настройки мержится в конфиг, не трогая движок.

    # Выхлоп и пороги.
    threshold = _clean(form.get("cover_threshold", ""))
    if threshold:
        data["cover_letter_threshold"] = int(threshold)
    output_lang = _clean(form.get("output_lang", ""))
    if output_lang:
        data["output_lang"] = output_lang
    if data["output_mode"] in ("bot", "both"):
        bot_token = _clean(form.get("bot_token", ""))
        if bot_token:
            data["bot_token"] = bot_token
    data["enable_contacts"] = bool(form.get("enable_contacts"))

    return data


def engine_config_from_form(
    form: FormLike,
) -> tuple[dict[str, Any], dict[str, str | None]]:
    """Разобрать форму страницы «AI · авторизация».

    Возвращает (`config_subset`, `secrets`): первое мержится в `config.json`
    (выбор движка, cli_tool, ollama/api поля, web-поиск), второе пишется в
    `.env` (токены/ключи авторизации — CLI читают их из окружения). Пустые
    секреты не возвращаются, чтобы не затирать ранее заданные.

    Маппинг радио `engine` → конфиг: claude/codex → `scoring_engine=cli` +
    `cli_tool`; ollama → `scoring_engine=ollama`. Движок `api_key` со страницы
    убран (доступен только ручной правкой config.json).
    """
    engine = _clean(form.get("engine", "")) or "claude"
    config: dict[str, Any] = {}
    secrets: dict[str, str | None] = {}

    if engine in ("claude", "codex"):
        config["scoring_engine"] = "cli"
        config["cli_tool"] = engine
        if engine == "claude":
            token = _clean(form.get("claude_token", ""))
            if token:
                secrets["CLAUDE_CODE_OAUTH_TOKEN"] = token
        else:
            key = _clean(form.get("codex_key", ""))
            if key:
                secrets["OPENAI_API_KEY"] = key
    elif engine == "ollama":
        config["scoring_engine"] = "ollama"
        model = _clean(form.get("ollama_model", ""))
        url = _clean(form.get("ollama_url", ""))
        key = _clean(form.get("ollama_key", ""))
        if model:
            config["ollama_model"] = model
        if url:  # пусто → облако (https://ollama.com) по умолчанию
            config["api_base_url"] = url
        if key:  # ключ Ollama Cloud — секрет, в .env, не в config.json
            secrets["OLLAMA_API_KEY"] = key

    # Web-поиск — общий для скоринга (анализ компании/контакты).
    ws_url = _clean(form.get("web_search_url", ""))
    if ws_url:
        config["web_search"] = {"provider": "searxng", "url": ws_url}

    return config, secrets
