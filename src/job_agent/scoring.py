"""Скоринг (стадия 5): финалист пре-фильтра → строгий `ScoreResult`.

Рендерит `prompts/scoring.md` под выбранное направление и текст вакансии, зовёт
AI-движок с разрешённым web-поиском (анализ компании, этап 1 промта), парсит и
валидирует строгий JSON-объект в `ScoreResult`. Устойчив к мусору: преамбула
вокруг JSON, markdown-обёртка, кривой/неполный объект → `None`, а не исключение —
стадия не падает на одной плохой вакансии.

При `multi_track_scoring=True` и нескольких кандидат-треках (их насчитал
пре-фильтр в пределах `multi_track_delta`) промт зовётся по каждому, берётся
результат с большим `overall`. Контракт промта (`prompts/scoring.md`) read-only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .config import Track
from .engines.base import Engine
from .models import RoutedVacancy, ScoreResult, Vacancy
from .prefilter import MapExample

__all__ = [
    "render_prompt",
    "parse_score_result",
    "score_vacancy",
    "score_routed",
]

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "scoring.md"


def _vacancy_text(vacancy: Vacancy) -> str:
    """Полный текст вакансии для скоринга (детальнее, чем для эмбеддинга)."""
    parts = [vacancy.title]
    if vacancy.company:
        parts.append(f"Компания: {vacancy.company}")
    if vacancy.salary:
        parts.append(f"Зарплата: {vacancy.salary}")
    if vacancy.link_or_contact:
        parts.append(f"Контакт/ссылка: {vacancy.link_or_contact}")
    if vacancy.description:
        parts.append(vacancy.description)
    return "\n".join(parts)


def _search_map_text(track_id: str, examples: Sequence[MapExample]) -> str:
    """Примеры карты поиска, релевантные треку (тег `track_id` + общие)."""
    relevant = [text for text, tid in examples if tid in (None, track_id)]
    return "\n".join(f"- {text}" for text in relevant)


def _disqualifiers(track: Track, global_disqualifiers: str | None) -> str:
    """Дисквалификаторы трека + глобальные, в один блок."""
    parts = [p for p in (track.disqualifiers, global_disqualifiers) if p]
    return "\n".join(parts)


def render_prompt(
    routed: RoutedVacancy,
    track: Track,
    *,
    track_resume: str,
    search_map_examples: Sequence[MapExample] = (),
    global_disqualifiers: str | None = None,
    output_lang: str = "ru",
) -> str:
    """Подставить данные трека и вакансии в шаблон `prompts/scoring.md`."""
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    vacancy = routed.vacancy
    return (
        template.replace("{{track_name}}", track.name)
        .replace("{{track_resume}}", track_resume)
        .replace("{{track_rubric}}", track.rubric or "")
        .replace(
            "{{track_disqualifiers}}",
            _disqualifiers(track, global_disqualifiers),
        )
        .replace("{{search_map}}", _search_map_text(track.id, search_map_examples))
        .replace("{{vacancy_text}}", _vacancy_text(vacancy))
        .replace("{{company_name}}", vacancy.company or "")
        .replace("{{output_lang}}", output_lang)
    )


def _strip_fences(text: str) -> str:
    """Убрать markdown-обёртку ```json ... ``` если она есть."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_object(text: str) -> object | None:
    """Вытащить JSON-объект из текста, терпимо к преамбуле вокруг него."""
    candidate = _strip_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None


def parse_score_result(text: str) -> ScoreResult | None:
    """Распарсить ответ движка в `ScoreResult`; мусор/неполнота → `None`."""
    data = _extract_object(text)
    if not isinstance(data, dict):
        return None
    try:
        return ScoreResult.model_validate(data)
    except Exception:
        return None


def score_vacancy(
    routed: RoutedVacancy,
    track: Track,
    engine: Engine,
    *,
    track_resume: str,
    search_map_examples: Sequence[MapExample] = (),
    global_disqualifiers: str | None = None,
    output_lang: str = "ru",
) -> ScoreResult | None:
    """Скорить одну вакансию против одного трека через движок (с web-поиском)."""
    prompt = render_prompt(
        routed,
        track,
        track_resume=track_resume,
        search_map_examples=search_map_examples,
        global_disqualifiers=global_disqualifiers,
        output_lang=output_lang,
    )
    response = engine.complete(prompt, web_search=True)
    return parse_score_result(response)


def score_routed(
    routed: RoutedVacancy,
    tracks_by_id: Mapping[str, Track],
    engine: Engine,
    *,
    track_resumes: Mapping[str, str],
    search_map_examples: Sequence[MapExample] = (),
    global_disqualifiers: str | None = None,
    multi_track_scoring: bool = False,
    output_lang: str = "ru",
) -> ScoreResult | None:
    """Скорить финалиста, выбрав направление (опц. мульти-трек по `overall`).

    Без `multi_track_scoring` — только `best_track`. С ним перебираются
    кандидат-треки, насчитанные пре-фильтром (`candidate_tracks`), и берётся
    результат с большим `overall`. Все парсы провалились → `None`.
    """
    if multi_track_scoring and routed.candidate_tracks:
        track_ids = routed.candidate_tracks
    else:
        track_ids = [routed.best_track]

    best: ScoreResult | None = None
    for track_id in track_ids:
        track = tracks_by_id.get(track_id)
        resume = track_resumes.get(track_id)
        if track is None or resume is None:
            continue
        result = score_vacancy(
            routed,
            track,
            engine,
            track_resume=resume,
            search_map_examples=search_map_examples,
            global_disqualifiers=global_disqualifiers,
            output_lang=output_lang,
        )
        if result is None:
            continue
        if best is None or result.scores.overall > best.scores.overall:
            best = result
    return best
