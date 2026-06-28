"""Тесты скоринга (стадия 5) — на фейк-движке, без сети."""

from __future__ import annotations

import json

from job_agent.config import Track
from job_agent.engines.fake import FakeEngine
from job_agent.models import RoutedVacancy, Vacancy
from job_agent.scoring import (
    parse_score_result,
    render_prompt,
    score_routed,
    score_vacancy,
)

VACANCY = Vacancy(
    title="Python-разработчик",
    company="Acme",
    link_or_contact="@hr_acme",
    salary="300к",
    description="Бэкенд на Python, удалёнка",
    source="@jobs",
    url="https://t.me/jobs/1",
)

ROUTED = RoutedVacancy(
    vacancy=VACANCY,
    best_track="backend",
    best_sim=0.7,
    map_fit_pre=60,
)

TRACK_BACKEND = Track(
    id="backend",
    name="Бэкенд",
    resume_path="resumes/backend.md",
    rubric="продуктовые команды, b2b",
    disqualifiers="без галер",
)

TRACK_DATA = Track(
    id="data",
    name="Дата",
    resume_path="resumes/data.md",
)


def _score_json(*, track: str = "Бэкенд", overall: int = 75) -> str:
    return json.dumps(
        {
            "track": track,
            "company_analysis": "scaleup, b2b SaaS",
            "company_confidence": "medium",
            "requirements": {"must": ["Python"], "nice": ["k8s"]},
            "matching": [
                {"requirement": "Python", "status": "full", "evidence": "5 лет"}
            ],
            "scores": {
                "must": 80,
                "nice": 50,
                "seniority": 70,
                "context": 65,
                "overall": overall,
                "map_fit": 60,
            },
            "score_method": "среднее взвешенное",
            "gaps": {"critical": [], "strategic": ["масштаб"], "cosmetic": []},
            "to_reach_100": ["добавить k8s"],
            "verdict": {
                "should_apply": True,
                "type": "precise_fit",
                "hr_screening_probability": "high",
                "final_stage_probability": "medium",
                "summary": "точное попадание",
            },
        },
        ensure_ascii=False,
    )


def test_render_prompt_substitutes_all_placeholders() -> None:
    prompt = render_prompt(
        ROUTED,
        TRACK_BACKEND,
        track_resume="мой опыт на python",
        search_map_examples=[("идеальная вакансия", "backend"), ("общий эталон", None)],
        global_disqualifiers="без переездов",
        output_lang="en",
    )
    for placeholder in (
        "{{track_name}}",
        "{{track_resume}}",
        "{{track_rubric}}",
        "{{track_disqualifiers}}",
        "{{search_map}}",
        "{{vacancy_text}}",
        "{{company_name}}",
        "{{output_lang}}",
    ):
        assert placeholder not in prompt
    assert "Бэкенд" in prompt
    assert "мой опыт на python" in prompt
    assert "продуктовые команды" in prompt
    assert "без галер" in prompt
    assert "без переездов" in prompt  # глобальные дисквалификаторы подмешаны
    assert "идеальная вакансия" in prompt
    assert "общий эталон" in prompt
    assert "Python-разработчик" in prompt
    assert "Acme" in prompt
    assert "en" in prompt


def test_search_map_filters_by_track() -> None:
    # пример другого трека не должен попасть в промт
    prompt = render_prompt(
        ROUTED,
        TRACK_BACKEND,
        track_resume="r",
        search_map_examples=[("чужой пример", "data"), ("свой пример", "backend")],
    )
    assert "свой пример" in prompt
    assert "чужой пример" not in prompt


def test_score_vacancy_parses_and_uses_web_search() -> None:
    engine = FakeEngine(_score_json())
    result = score_vacancy(ROUTED, TRACK_BACKEND, engine, track_resume="r")
    assert result is not None
    assert result.scores.overall == 75
    assert result.verdict.type == "precise_fit"
    assert result.track == "Бэкенд"
    # web-поиск разрешён движку на анализе компании
    assert engine.calls[0][1] is True


def test_parse_tolerates_fences_and_preamble() -> None:
    fenced = "```json\n" + _score_json() + "\n```"
    assert parse_score_result(fenced) is not None
    pre = "Вот результат:\n" + _score_json() + "\nГотово."
    assert parse_score_result(pre) is not None


def test_parse_garbage_returns_none() -> None:
    assert parse_score_result("это не json") is None
    assert parse_score_result("") is None
    assert parse_score_result("[1, 2, 3]") is None  # массив вместо объекта


def test_parse_invalid_percent_returns_none() -> None:
    bad = json.loads(_score_json())
    bad["scores"]["overall"] = 150  # вне 0–100
    assert parse_score_result(json.dumps(bad, ensure_ascii=False)) is None


def test_score_garbage_response_returns_none() -> None:
    engine = FakeEngine("движок поломался")
    assert score_vacancy(ROUTED, TRACK_BACKEND, engine, track_resume="r") is None


def test_score_routed_single_track() -> None:
    engine = FakeEngine(_score_json())
    result = score_routed(
        ROUTED,
        {"backend": TRACK_BACKEND},
        engine,
        track_resumes={"backend": "r"},
    )
    assert result is not None
    assert engine.call_count == 1  # только best_track


def test_score_routed_multi_track_picks_higher_overall() -> None:
    routed = RoutedVacancy(
        vacancy=VACANCY,
        best_track="backend",
        best_sim=0.7,
        map_fit_pre=60,
        candidate_tracks=["backend", "data"],
    )
    engine = FakeEngine(
        responses=[
            _score_json(track="Бэкенд", overall=70),
            _score_json(track="Дата", overall=85),
        ]
    )
    result = score_routed(
        routed,
        {"backend": TRACK_BACKEND, "data": TRACK_DATA},
        engine,
        track_resumes={"backend": "r1", "data": "r2"},
        multi_track_scoring=True,
    )
    assert result is not None
    assert engine.call_count == 2
    assert result.scores.overall == 85
    assert result.track == "Дата"


def test_score_routed_multi_track_flag_off_scores_only_best() -> None:
    routed = RoutedVacancy(
        vacancy=VACANCY,
        best_track="backend",
        best_sim=0.7,
        map_fit_pre=60,
        candidate_tracks=["backend", "data"],
    )
    engine = FakeEngine(_score_json())
    score_routed(
        routed,
        {"backend": TRACK_BACKEND, "data": TRACK_DATA},
        engine,
        track_resumes={"backend": "r1", "data": "r2"},
        multi_track_scoring=False,
    )
    assert engine.call_count == 1  # флаг выкл → только best_track


def test_score_routed_all_parses_fail_returns_none() -> None:
    engine = FakeEngine("мусор")
    result = score_routed(
        ROUTED,
        {"backend": TRACK_BACKEND},
        engine,
        track_resumes={"backend": "r"},
    )
    assert result is None
