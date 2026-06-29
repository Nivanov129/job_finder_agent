"""Модели данных пайплайна (pydantic v2).

Сквозные структуры стадий: сырьё коллектора → нормализованная вакансия →
роутинг пре-фильтра → строгий результат скоринга → обогащённый результат.

`ScoreResult` точно повторяет схему вывода `prompts/scoring.md`; все проценты
валидируются в диапазоне 0–100. `Track` берётся из `config.py` (единый источник).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import Track

__all__ = [
    "RawPost",
    "Vacancy",
    "Track",
    "RoutedVacancy",
    "Requirements",
    "MatchItem",
    "Scores",
    "Gaps",
    "Verdict",
    "ScoreResult",
    "ContactCandidate",
    "ContactResult",
    "EnrichedResult",
]

def _percent_field(description: str) -> int:
    return Field(ge=0, le=100, description=description)


class RawPost(BaseModel):
    """Сырой пост из коллектора (стадия 1 — сбор)."""

    model_config = ConfigDict(extra="forbid")

    raw_text: str
    source: str
    url: str | None = None
    date: datetime | None = None


class Vacancy(BaseModel):
    """Нормализованная вакансия (стадия 2) + провенанс из `RawPost`.

    Поля `title..description` — строго из `prompts/normalize.md`; `source/url/date`
    дописывает оркестратор из исходного поста (нужны для выхлопа xlsx/бота).
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    company: str | None = None
    link_or_contact: str | None = None
    salary: str | None = None
    description: str = ""

    source: str | None = None
    url: str | None = None
    date: datetime | None = None


class RoutedVacancy(BaseModel):
    """Вакансия после пре-фильтра и роутинга (стадия 4).

    `best_track` — id выбранного направления; `best_sim` — косинус резюме↔вакансия;
    `map_fit_pre` — предварительный процент карты до скоринга; `candidate_tracks` —
    топ-треки для опц. мульти-трек скоринга (в пределах `multi_track_delta`).
    """

    model_config = ConfigDict(extra="forbid")

    vacancy: Vacancy
    best_track: str
    best_sim: float = Field(ge=-1.0, le=1.0)
    map_fit_pre: int = _percent_field("предварительный процент карты (0–100)")
    candidate_tracks: list[str] = Field(default_factory=list)


# --- ScoreResult: дословно по схеме prompts/scoring.md -----------------------

Confidence = Literal["high", "medium", "low"]


class Requirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    must: list[str] = Field(default_factory=list)
    nice: list[str] = Field(default_factory=list)


class MatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement: str
    status: Literal["full", "partial", "none"]
    evidence: str = ""


class Scores(BaseModel):
    """Шесть процентов скоринга, каждый 0–100."""

    model_config = ConfigDict(extra="forbid")

    must: int = _percent_field("% соответствия обязательным требованиям")
    nice: int = _percent_field("% соответствия желательным")
    seniority: int = _percent_field("% уровню ответственности")
    context: int = _percent_field("% контексту компании")
    overall: int = _percent_field("итоговый общий процент (резюме %)")
    map_fit: int = _percent_field("% соответствия карте (хочу ли)")


class Gaps(BaseModel):
    model_config = ConfigDict(extra="forbid")

    critical: list[str] = Field(default_factory=list)
    strategic: list[str] = Field(default_factory=list)
    cosmetic: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_apply: bool
    type: Literal["stretch", "precise_fit"]
    hr_screening_probability: Confidence
    final_stage_probability: Confidence
    summary: str


class ScoreResult(BaseModel):
    """Строгий результат скоринга (стадия 5) — точно схема `prompts/scoring.md`."""

    model_config = ConfigDict(extra="forbid")

    track: str
    company_analysis: str
    company_confidence: Confidence
    requirements: Requirements
    matching: list[MatchItem] = Field(default_factory=list)
    scores: Scores
    score_method: str
    gaps: Gaps
    to_reach_100: list[str] = Field(default_factory=list)
    verdict: Verdict


# --- Обогащение --------------------------------------------------------------


class ContactCandidate(BaseModel):
    """Кандидат-контакт из `prompts/contact-search.md`."""

    model_config = ConfigDict(extra="forbid")

    name: str
    role: str = ""
    source: str = ""
    link: str = ""
    confidence: Confidence = "low"


class ContactResult(BaseModel):
    """Результат контакт-ассиста (опц., стадия 6). Без отправки — только данные."""

    model_config = ConfigDict(extra="forbid")

    target_roles: list[str] = Field(default_factory=list)
    queries_used: list[str] = Field(default_factory=list)
    candidates: list[ContactCandidate] = Field(default_factory=list)
    fallback_paths: list[str] = Field(default_factory=list)
    draft_message: str = ""


class InvestigatedContact(BaseModel):
    """Контакт из инвестигатора (доп. движок поиска контактов «с именем»).

    Богаче `ContactCandidate`: явный маршрут связи, числовой confidence,
    градация доказательств и обоснование (методика recruiting-contact-investigator).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    role: str = ""
    contact_route: str = ""  # TG @handle / email / LinkedIn DM / …
    link: str = ""
    confidence: int = 0  # 0..100
    evidence_grade: str = ""  # verified | indexed | cross-source | unverified
    rationale: str = ""


class ContactInvestigation(BaseModel):
    """Отчёт доп-движка контактов: ранжированные контакты + аудит + next actions."""

    model_config = ConfigDict(extra="forbid")

    contacts: list[InvestigatedContact] = Field(default_factory=list)
    evidence_checked: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class EnrichedResult(BaseModel):
    """Финальный результат по вакансии (стадия 6→7): скоринг + обогащение.

    `cover_letter` есть только при `overall >= cover_letter_threshold` и шаблоне трека;
    `contacts` — только при `enable_contacts`. `investigation` — доп. движок
    контактов (опц., `enable_contact_investigator`). Идёт и в xlsx, и в карточку бота.
    """

    model_config = ConfigDict(extra="forbid")

    vacancy: Vacancy
    score: ScoreResult
    cover_letter: str | None = None
    contacts: ContactResult | None = None
    investigation: ContactInvestigation | None = None
