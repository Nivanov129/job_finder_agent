"""Загрузчик и валидатор конфига участника.

Читает JSON, валидирует против `config.schema.json` (jsonschema, draft 2020-12),
возвращает типизированный `Config` (pydantic v2). Ошибки валидации — внятные.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel, ConfigDict, Field

# config.py -> job_agent -> src -> <repo root>
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config.schema.json"


class ConfigError(ValueError):
    """Внятная ошибка валидации/загрузки конфига."""


class Track(BaseModel):
    """Одно направление поиска."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    resume_path: str
    cover_template_path: str | None = None
    rubric: str | None = None
    role_gate: list[str] = Field(default_factory=list)
    disqualifiers: str | None = None


class SearchMapExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    track_id: str | None = None


class SearchMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = None
    examples: list[SearchMapExample] = Field(default_factory=list)


class TgChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str
    private: bool = False


class WebSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "searxng"
    url: str | None = None
    api_key: str | None = None


class TelethonCreds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_id: str | None = None
    api_hash: str | None = None
    session: str | None = None


class Config(BaseModel):
    """Типизированный конфиг участника."""

    model_config = ConfigDict(extra="forbid")

    version: int
    tracks: list[Track]
    scoring_engine: str
    output_mode: str

    search_map: SearchMap | None = None
    global_role_gate: list[str] = Field(default_factory=list)
    global_disqualifiers: str | None = None

    multi_track_scoring: bool = False
    multi_track_delta: float = 0.05
    # Порог близости пре-фильтра; калибруется командой `calibrate` (Task 4.4).
    # Дефолт совпадает с prefilter.DEFAULT_MIN_SIM (без импорта — избегаем цикла).
    min_sim: float = 0.30

    tg_channels: list[TgChannel] = Field(default_factory=list)
    use_aggregators: bool = True
    # Доп. источник вакансий: дорки по ролям на LinkedIn через web-поиск (SearXNG).
    use_linkedin: bool = False
    # Карьерные сайты компаний (домены, напр. "career.ozon.ru"): ищем на них
    # вакансии дорком `"<роль>" site:<домен>` через web-поиск. Роли — из резюме
    # (role_gate). Пустой список — источник выключен.
    career_sites: list[str] = Field(default_factory=list)

    cli_tool: str | None = None
    api_base_url: str | None = None
    api_key: str | None = None
    ollama_model: str | None = None

    web_search: WebSearch | None = None

    backfill_days: int = 14
    cover_letter_threshold: int = 70
    output_lang: str = "ru"
    bot_token: str | None = None
    # Личный чат владельца для бот-уведомлений (новые вакансии в фоне). Токен
    # бота — секрет, живёт в `.env` (TELEGRAM_BOT_TOKEN), а сюда пишем chat_id
    # (не секрет), пойманный через getUpdates. None — уведомления выключены.
    owner_chat_id: int | str | None = None
    telethon_creds: TelethonCreds | None = None
    enable_contacts: bool = False
    # Доп-движок контактов (инвестигатор): расследование контактов с confidence/
    # доказательствами. Дороже (отдельный web-вызов на вакансию), потому opt-in.
    enable_contact_investigator: bool = False
    # Скорость: параллельные AI-вызовы (нормализация/скоринг) и грубый фильтр по
    # названию должности (из резюме) ДО нормализации — чтобы не гонять AI зря.
    parallelism: int = 4
    title_prefilter: bool = True
    # Локальная модель эмбеддингов для пред-фильтра. False — фильтр только по
    # названию+ролям (без локальной модели, чисто облако), но в скоринг уходит
    # чуть больше вакансий.
    use_embeddings: bool = True
    # Режим агента: пауза между авто-прогонами (минуты). Каждый прогон догоняет
    # вакансии с момента прошлого (по времени последнего прогона).
    agent_interval_minutes: int = 30

    @property
    def is_single_track(self) -> bool:
        """True, если направление ровно одно (схлопывает UI и выхлоп)."""
        return len(self.tracks) == 1


def _load_schema() -> dict[str, Any]:
    try:
        return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - инвариант репо
        raise ConfigError(f"Схема конфига не найдена: {_SCHEMA_PATH}") from exc


def _format_validation_error(error: jsonschema.ValidationError) -> str:
    location = "/".join(str(p) for p in error.absolute_path) or "<корень>"
    return f"конфиг невалиден по схеме (поле: {location}): {error.message}"


def load_config(path: str | Path) -> Config:
    """Прочитать, провалидировать и вернуть типизированный конфиг.

    Сначала JSON-схема (структурные ошибки с указанием поля), затем pydantic.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"Файл конфига не найден: {path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Конфиг не является валидным JSON ({path}): {exc}") from exc

    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        details = "; ".join(_format_validation_error(e) for e in errors)
        raise ConfigError(details)

    try:
        return Config.model_validate(data)
    except Exception as exc:  # pragma: no cover - схема уже отсекла структурные ошибки
        raise ConfigError(f"Не удалось построить Config: {exc}") from exc
