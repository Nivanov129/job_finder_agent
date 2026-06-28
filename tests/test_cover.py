"""Тесты сопроводительного (стадия 6) — на фейк-движке, без сети."""

from __future__ import annotations

from job_agent.engines.fake import FakeEngine
from job_agent.enrich.cover import (
    render_prompt,
    should_write_cover,
    write_cover_letter,
)
from job_agent.models import (
    Gaps,
    Requirements,
    ScoreResult,
    Scores,
    Vacancy,
    Verdict,
)

VACANCY = Vacancy(
    title="Python-разработчик",
    company="Acme",
    link_or_contact="@hr_acme",
    description="Бэкенд на Python, удалёнка",
    source="@jobs",
    url="https://t.me/jobs/1",
)

TEMPLATE = (
    "Здравствуйте! Я [название должности] с [X] годами опыта в [сфера].\n"
    "[ссылка на вакансию]"
)
RESUME = "Иван Иванов, бэкенд-разработчик, 6 лет, Python/Django."


def _score(overall: int = 75) -> ScoreResult:
    return ScoreResult(
        track="backend",
        company_analysis="scaleup b2b",
        company_confidence="medium",
        requirements=Requirements(must=["Python"], nice=["k8s"]),
        scores=Scores(
            must=80, nice=60, seniority=70, context=70, overall=overall, map_fit=65
        ),
        score_method="weighted",
        gaps=Gaps(strategic=["нет k8s в проде"]),
        to_reach_100=["подсветить опыт нагрузок"],
        verdict=Verdict(
            should_apply=True,
            type="precise_fit",
            hr_screening_probability="high",
            final_stage_probability="medium",
            summary="хороший фит",
        ),
    )


def test_should_write_cover_gate() -> None:
    score_hi = _score(overall=75)
    score_lo = _score(overall=60)
    # выше порога + есть шаблон → пишем
    assert should_write_cover(score_hi, cover_template=TEMPLATE, threshold=70)
    # ниже порога → не пишем
    assert not should_write_cover(score_lo, cover_template=TEMPLATE, threshold=70)
    # нет/пустой шаблон → не пишем даже выше порога
    assert not should_write_cover(score_hi, cover_template=None, threshold=70)
    assert not should_write_cover(score_hi, cover_template="   ", threshold=70)


def test_below_threshold_returns_none() -> None:
    engine = FakeEngine(response="НЕ ДОЛЖНО ВЫЗВАТЬСЯ")
    letter = write_cover_letter(
        _score(overall=60),
        VACANCY,
        engine,
        cover_template=TEMPLATE,
        track_resume=RESUME,
        threshold=70,
    )
    assert letter is None
    assert engine.call_count == 0  # движок не зовётся ниже порога


def test_no_template_returns_none() -> None:
    engine = FakeEngine(response="текст")
    letter = write_cover_letter(
        _score(overall=90),
        VACANCY,
        engine,
        cover_template=None,
        track_resume=RESUME,
        threshold=70,
    )
    assert letter is None
    assert engine.call_count == 0


def test_above_threshold_returns_text() -> None:
    engine = FakeEngine(
        response="Здравствуйте! Я Python-разработчик с 6 годами опыта.\nГотов созвониться."
    )
    letter = write_cover_letter(
        _score(overall=85),
        VACANCY,
        engine,
        cover_template=TEMPLATE,
        track_resume=RESUME,
        threshold=70,
    )
    assert letter is not None
    assert "Python-разработчик" in letter
    assert engine.call_count == 1
    # сопроводительное не требует web-поиска
    assert engine.calls[0][1] is False


def test_strips_markdown_fences() -> None:
    engine = FakeEngine(response="```\nТекст письма.\n```")
    letter = write_cover_letter(
        _score(overall=85),
        VACANCY,
        engine,
        cover_template=TEMPLATE,
        track_resume=RESUME,
        threshold=70,
    )
    assert letter == "Текст письма."


def test_empty_engine_response_returns_none() -> None:
    engine = FakeEngine(response="   ")
    letter = write_cover_letter(
        _score(overall=85),
        VACANCY,
        engine,
        cover_template=TEMPLATE,
        track_resume=RESUME,
        threshold=70,
    )
    assert letter is None


def test_render_prompt_fills_placeholders() -> None:
    prompt = render_prompt(
        _score(overall=85),
        VACANCY,
        cover_template=TEMPLATE,
        track_resume=RESUME,
    )
    # шаблон и резюме подставлены
    assert "Иван Иванов" in prompt
    assert "[название должности]" in prompt  # шаблон вошёл как каркас
    # ссылка вакансии — из url
    assert "https://t.me/jobs/1" in prompt
    # срез скоринга подставлен (must / strategic / to_reach_100)
    assert "Python" in prompt
    assert "нет k8s в проде" in prompt
    assert "подсветить опыт нагрузок" in prompt
    # плейсхолдеры промта не остались незаполненными
    assert "{{cover_template}}" not in prompt
    assert "{{scoring_result}}" not in prompt
    assert "{{vacancy_link}}" not in prompt
