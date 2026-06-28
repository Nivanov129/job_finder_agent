"""Тесты нормализации (стадия 2) — на фейк-движке, без сети."""

from __future__ import annotations

from datetime import UTC, datetime

from job_agent.engines.fake import FakeEngine
from job_agent.models import RawPost, Vacancy
from job_agent.normalize import (
    normalize_post,
    normalize_posts,
    parse_vacancies,
    render_prompt,
)

POST = RawPost(
    raw_text="Ищем Python-разработчика в Acme. Зарплата 300к. Откликаться @hr_acme",
    source="@jobs_channel",
    url="https://t.me/jobs_channel/42",
    date=datetime(2026, 6, 1, tzinfo=UTC),
)

ONE_VACANCY = """
[
  {
    "title": "Python-разработчик",
    "company": "Acme",
    "link_or_contact": "@hr_acme",
    "salary": "300к",
    "description": "Бэкенд на Python, удалёнка"
  }
]
"""


def test_render_prompt_substitutes_fields() -> None:
    prompt = render_prompt(POST, output_lang="en")
    assert "{{raw_text}}" not in prompt
    assert "{{source}}" not in prompt
    assert "{{output_lang}}" not in prompt
    assert POST.raw_text in prompt
    assert POST.source in prompt
    assert "en" in prompt


def test_normalize_post_parses_single_vacancy() -> None:
    engine = FakeEngine(ONE_VACANCY)
    vacancies = normalize_post(POST, engine)
    assert len(vacancies) == 1
    v = vacancies[0]
    assert v == Vacancy(
        title="Python-разработчик",
        company="Acme",
        link_or_contact="@hr_acme",
        salary="300к",
        description="Бэкенд на Python, удалёнка",
        source="@jobs_channel",
        url="https://t.me/jobs_channel/42",
        date=datetime(2026, 6, 1, tzinfo=UTC),
    )
    # движок вызван ровно один раз с подставленным промтом
    assert engine.call_count == 1
    assert POST.raw_text in (engine.last_prompt or "")


def test_normalize_post_multiple_vacancies() -> None:
    response = """[
      {"title": "A", "company": "X", "description": "d1"},
      {"title": "B", "company": null, "description": "d2"}
    ]"""
    vacancies = normalize_post(POST, FakeEngine(response))
    assert [v.title for v in vacancies] == ["A", "B"]
    assert vacancies[1].company is None


def test_non_vacancy_returns_empty() -> None:
    # промт велит вернуть [] для не-вакансии
    assert normalize_post(POST, FakeEngine("[]")) == []


def test_garbage_response_returns_empty() -> None:
    assert normalize_post(POST, FakeEngine("это не json вовсе")) == []
    assert normalize_post(POST, FakeEngine("")) == []
    # объект вместо массива → пусто
    assert normalize_post(POST, FakeEngine('{"title": "x"}')) == []


def test_markdown_fenced_json_is_parsed() -> None:
    response = "```json\n" + ONE_VACANCY.strip() + "\n```"
    vacancies = normalize_post(POST, FakeEngine(response))
    assert len(vacancies) == 1
    assert vacancies[0].title == "Python-разработчик"


def test_preamble_around_array_is_tolerated() -> None:
    response = 'Вот результат:\n[{"title": "Z", "description": "d"}]\nГотово.'
    vacancies = normalize_post(POST, FakeEngine(response))
    assert [v.title for v in vacancies] == ["Z"]


def test_items_without_title_skipped() -> None:
    response = """[
      {"company": "NoTitle", "description": "d"},
      {"title": "   ", "description": "blank"},
      {"title": "Real", "description": "ok"}
    ]"""
    vacancies = parse_vacancies(response, POST)
    assert [v.title for v in vacancies] == ["Real"]


def test_provenance_filled_from_post() -> None:
    v = normalize_post(POST, FakeEngine(ONE_VACANCY))[0]
    assert v.source == POST.source
    assert v.url == POST.url
    assert v.date == POST.date


def test_normalize_posts_flattens_all() -> None:
    other = RawPost(raw_text="another", source="@x")
    engine = FakeEngine(
        responses=[
            '[{"title": "A", "description": "d"}]',
            '[{"title": "B", "description": "d"}]',
        ]
    )
    vacancies = normalize_posts([POST, other], engine)
    assert [v.title for v in vacancies] == ["A", "B"]
    assert vacancies[1].source == "@x"
