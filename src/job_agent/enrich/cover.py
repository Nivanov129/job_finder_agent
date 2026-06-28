"""Сопроводительное (стадия 6): правка шаблона трека под вакансию.

Рендерит `prompts/cover-letter.md`, зовёт AI-движок, возвращает текст письма.
Не генерим с нуля — адаптируем `cover_template_path` трека (структура, тон),
это экономит токены и держит голос пользователя.

Гейт (см. `prompts/cover-letter.md` и `EnrichedResult.cover_letter`): письмо
готовится только когда `score.scores.overall >= cover_letter_threshold` И у трека
есть шаблон (`cover_template_path` → непустой `cover_template`). Иначе → `None`,
поле остаётся пустым и в xlsx, и в кнопке бота. Контракт промта read-only.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..engines.base import Engine
from ..models import ScoreResult, Vacancy

__all__ = [
    "should_write_cover",
    "render_prompt",
    "write_cover_letter",
]

_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "cover-letter.md"


def should_write_cover(
    score: ScoreResult,
    *,
    cover_template: str | None,
    threshold: int,
) -> bool:
    """Готовить ли сопроводительное: overall ≥ порога И есть непустой шаблон."""
    if cover_template is None or not cover_template.strip():
        return False
    return score.scores.overall >= threshold


def _vacancy_text(vacancy: Vacancy) -> str:
    """Текст вакансии для адаптации шаблона (как в скоринге, без зарплаты-шума)."""
    parts = [vacancy.title]
    if vacancy.company:
        parts.append(f"Компания: {vacancy.company}")
    if vacancy.link_or_contact:
        parts.append(f"Контакт/ссылка: {vacancy.link_or_contact}")
    if vacancy.description:
        parts.append(vacancy.description)
    return "\n".join(parts)


def _vacancy_link(vacancy: Vacancy) -> str:
    """Ссылка на вакансию для мессенджеров: url приоритетнее контакта."""
    return vacancy.url or vacancy.link_or_contact or ""


def _scoring_payload(score: ScoreResult) -> str:
    """Срез скоринга, нужный промту: must-требования, стратегич. гэпы, to_reach_100."""
    payload = {
        "requirements": {"must": score.requirements.must},
        "gaps": {"strategic": score.gaps.strategic},
        "to_reach_100": score.to_reach_100,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_prompt(
    score: ScoreResult,
    vacancy: Vacancy,
    *,
    cover_template: str,
    track_resume: str,
    output_lang: str = "ru",
) -> str:
    """Подставить шаблон трека, резюме и вакансию в `prompts/cover-letter.md`."""
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{{cover_template}}", cover_template)
        .replace("{{track_resume}}", track_resume)
        .replace("{{vacancy_text}}", _vacancy_text(vacancy))
        .replace("{{company_name}}", vacancy.company or "")
        .replace("{{vacancy_link}}", _vacancy_link(vacancy))
        .replace("{{scoring_result}}", _scoring_payload(score))
        .replace("{{output_lang}}", output_lang)
    )


def _strip_fences(text: str) -> str:
    """Снять markdown-обёртку ``` ... ```, если движок завернул письмо целиком."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def write_cover_letter(
    score: ScoreResult,
    vacancy: Vacancy,
    engine: Engine,
    *,
    cover_template: str | None,
    track_resume: str,
    threshold: int,
    output_lang: str = "ru",
) -> str | None:
    """Подготовить сопроводительное; ниже порога/без шаблона → `None`.

    Письмо — это правка `cover_template` под вакансию (см. промт). Web-поиск не
    нужен: только локальные данные трека и вакансии. Пустой ответ движка → `None`.
    """
    if not should_write_cover(score, cover_template=cover_template, threshold=threshold):
        return None
    assert cover_template is not None  # гарантировано should_write_cover
    prompt = render_prompt(
        score,
        vacancy,
        cover_template=cover_template,
        track_resume=track_resume,
        output_lang=output_lang,
    )
    response = engine.complete(prompt)
    letter = _strip_fences(response)
    return letter or None
