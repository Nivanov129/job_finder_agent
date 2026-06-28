"""Тесты моделей данных пайплайна: валидация диапазонов и обязательных полей."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_agent.models import (
    EnrichedResult,
    RawPost,
    RoutedVacancy,
    ScoreResult,
    Track,
    Vacancy,
)


def _valid_score_dict() -> dict:
    """Минимально валидный результат скоринга по схеме prompts/scoring.md."""
    return {
        "track": "Backend",
        "company_analysis": "scaleup, b2b fintech",
        "company_confidence": "medium",
        "requirements": {"must": ["python"], "nice": ["go"]},
        "matching": [
            {"requirement": "python", "status": "full", "evidence": "5 лет"}
        ],
        "scores": {
            "must": 80,
            "nice": 50,
            "seniority": 70,
            "context": 60,
            "overall": 75,
            "map_fit": 90,
        },
        "score_method": "взвешенно",
        "gaps": {"critical": [], "strategic": ["go"], "cosmetic": []},
        "to_reach_100": ["добавить go"],
        "verdict": {
            "should_apply": True,
            "type": "stretch",
            "hr_screening_probability": "high",
            "final_stage_probability": "medium",
            "summary": "дотянись, это твоё",
        },
    }


def test_raw_post_minimal() -> None:
    post = RawPost(raw_text="ищем backend", source="@jobs")
    assert post.url is None
    assert post.date is None


def test_vacancy_requires_title() -> None:
    with pytest.raises(ValidationError):
        Vacancy()  # type: ignore[call-arg]


def test_vacancy_normalize_fields() -> None:
    v = Vacancy(title="Backend Engineer", company="Acme", description="python")
    assert v.salary is None
    assert v.source is None


def test_track_reexported_from_config() -> None:
    track = Track(id="backend", name="Backend", resume_path="./r.pdf")
    assert track.id == "backend"


def test_score_result_parses_full_schema() -> None:
    res = ScoreResult.model_validate(_valid_score_dict())
    assert res.scores.overall == 75
    assert res.scores.map_fit == 90
    assert res.verdict.type == "stretch"
    assert res.matching[0].status == "full"


def test_scores_reject_above_100() -> None:
    data = _valid_score_dict()
    data["scores"]["overall"] = 101
    with pytest.raises(ValidationError, match="overall"):
        ScoreResult.model_validate(data)


def test_scores_reject_negative() -> None:
    data = _valid_score_dict()
    data["scores"]["map_fit"] = -1
    with pytest.raises(ValidationError, match="map_fit"):
        ScoreResult.model_validate(data)


def test_score_result_bad_verdict_enum() -> None:
    data = _valid_score_dict()
    data["verdict"]["type"] = "maybe"
    with pytest.raises(ValidationError, match="type"):
        ScoreResult.model_validate(data)


def test_score_result_rejects_unknown_field() -> None:
    data = _valid_score_dict()
    data["surprise"] = True
    with pytest.raises(ValidationError):
        ScoreResult.model_validate(data)


def test_routed_vacancy_percent_and_sim_bounds() -> None:
    vac = Vacancy(title="Backend", description="python")
    rv = RoutedVacancy(vacancy=vac, best_track="backend", best_sim=0.42, map_fit_pre=80)
    assert rv.candidate_tracks == []

    with pytest.raises(ValidationError, match="map_fit_pre"):
        RoutedVacancy(vacancy=vac, best_track="backend", best_sim=0.4, map_fit_pre=120)

    with pytest.raises(ValidationError, match="best_sim"):
        RoutedVacancy(vacancy=vac, best_track="backend", best_sim=2.0, map_fit_pre=80)


def test_enriched_result_defaults() -> None:
    vac = Vacancy(title="Backend", description="python")
    enriched = EnrichedResult(vacancy=vac, score=ScoreResult.model_validate(_valid_score_dict()))
    assert enriched.cover_letter is None
    assert enriched.contacts is None
