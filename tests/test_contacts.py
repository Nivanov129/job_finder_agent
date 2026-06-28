"""Тесты контакт-ассиста (стадия 6, опц.) — на фейках движка и web-поиска, без сети."""

from __future__ import annotations

import json

from job_agent.engines.fake import FakeEngine
from job_agent.enrich.contacts import (
    build_queries,
    find_contacts,
    parse_contact_result,
    render_prompt,
)
from job_agent.models import ContactResult, Vacancy
from job_agent.websearch.base import SearchResult
from job_agent.websearch.fake import FakeSearcher

VACANCY = Vacancy(
    title="Python-разработчик",
    company="Acme",
    link_or_contact="@hr_acme",
    description="Бэкенд на Python, удалёнка",
    source="@jobs",
    url="https://t.me/jobs/1",
)

VALID_JSON = json.dumps(
    {
        "target_roles": ["recruiter", "head of backend"],
        "queries_used": ["site:linkedin.com Acme рекрутер"],
        "candidates": [
            {
                "name": "Анна Рекрутова",
                "role": "Talent Acquisition",
                "source": "habr.career",
                "link": "https://career.habr.com/anna",
                "confidence": "medium",
            }
        ],
        "fallback_paths": ["написать в общий HR-канал"],
        "draft_message": "Здравствуйте, Анна! Заинтересовала вакансия Python-разработчика.",
    },
    ensure_ascii=False,
)


def test_build_queries_boolean_and_sites() -> None:
    queries = build_queries("Python-разработчик", "Acme")
    joined = "\n".join(queries)
    assert "site:linkedin.com" in joined
    assert "site:habr.career" in joined
    assert "site:t.me" in joined
    assert "Acme" in joined
    assert "Python-разработчик" in joined


def test_build_queries_empty_company_returns_nothing() -> None:
    assert build_queries("Python", "") == []
    assert build_queries("Python", "   ") == []


def test_disabled_returns_none_without_calls() -> None:
    engine = FakeEngine(response="НЕ ДОЛЖНО ВЫЗВАТЬСЯ")
    searcher = FakeSearcher(results=[SearchResult(title="x", url="http://x")])
    result = find_contacts(
        VACANCY,
        engine,
        searcher,
        track_name="backend",
        enable_contacts=False,
    )
    assert result is None
    assert engine.call_count == 0
    assert searcher.call_count == 0


def test_enabled_returns_contact_result() -> None:
    engine = FakeEngine(response=VALID_JSON)
    searcher = FakeSearcher(
        results=[
            SearchResult(
                title="Анна Рекрутова — Acme",
                url="https://career.habr.com/anna",
                snippet="Talent Acquisition в Acme",
            )
        ]
    )
    result = find_contacts(
        VACANCY,
        engine,
        searcher,
        track_name="backend",
        enable_contacts=True,
    )
    assert isinstance(result, ContactResult)
    assert result.candidates[0].name == "Анна Рекрутова"
    assert result.draft_message
    # web-поиск отработал по каждому булеву запросу
    assert searcher.call_count == len(build_queries(VACANCY.title, VACANCY.company or ""))
    # движок зван один раз и сам в web не ходит — заземление уже собрано
    assert engine.call_count == 1
    assert engine.calls[0][1] is False
    # выдача подмешана в промт (заземление)
    assert "career.habr.com/anna" in engine.last_prompt


def test_grounding_includes_queries_and_snippet() -> None:
    engine = FakeEngine(response=VALID_JSON)
    searcher = FakeSearcher(
        results=[SearchResult(title="T", url="http://u", snippet="сниппет про найм")]
    )
    find_contacts(
        VACANCY,
        engine,
        searcher,
        track_name="backend",
        enable_contacts=True,
    )
    prompt = engine.last_prompt
    assert "Булевые запросы" in prompt
    assert "сниппет про найм" in prompt


def test_empty_search_yields_fallback_hint() -> None:
    engine = FakeEngine(response=VALID_JSON)
    searcher = FakeSearcher(results=[])
    find_contacts(
        VACANCY,
        engine,
        searcher,
        track_name="backend",
        enable_contacts=True,
    )
    assert "Выдача пуста" in engine.last_prompt


def test_no_company_returns_none() -> None:
    engine = FakeEngine(response=VALID_JSON)
    searcher = FakeSearcher(results=[])
    vacancy = Vacancy(title="Python", company=None)
    result = find_contacts(
        vacancy,
        engine,
        searcher,
        track_name="backend",
        enable_contacts=True,
    )
    assert result is None
    assert engine.call_count == 0
    assert searcher.call_count == 0


def test_garbage_json_returns_none() -> None:
    engine = FakeEngine(response="не json вообще")
    searcher = FakeSearcher(results=[])
    result = find_contacts(
        VACANCY,
        engine,
        searcher,
        track_name="backend",
        enable_contacts=True,
    )
    assert result is None


def test_parse_contact_result_strips_fences() -> None:
    text = f"```json\n{VALID_JSON}\n```"
    result = parse_contact_result(text)
    assert isinstance(result, ContactResult)
    assert result.target_roles == ["recruiter", "head of backend"]


def test_parse_contact_result_with_preamble() -> None:
    text = f"Вот результат:\n{VALID_JSON}\nконец"
    result = parse_contact_result(text)
    assert isinstance(result, ContactResult)
    assert result.candidates[0].confidence == "medium"


def test_render_prompt_fills_placeholders() -> None:
    prompt = render_prompt(
        VACANCY,
        track_name="backend",
        region="Москва",
        output_lang="ru",
    )
    assert "Python-разработчик" in prompt
    assert "Acme" in prompt
    assert "Москва" in prompt
    assert "backend" in prompt
    assert "https://t.me/jobs/1" in prompt
    assert "{{role}}" not in prompt
    assert "{{company_name}}" not in prompt
    assert "{{region}}" not in prompt
    assert "{{vacancy_link}}" not in prompt
    assert "{{track_name}}" not in prompt
    assert "{{output_lang}}" not in prompt
