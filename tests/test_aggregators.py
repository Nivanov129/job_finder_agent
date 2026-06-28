"""Тесты коллекторов агрегаторов (vseti HTML, getmatch JSON) на фикстурах, без сети."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from job_agent.collectors.getmatch import GetmatchCollector, parse_getmatch_json
from job_agent.collectors.habr import HabrCollector, parse_habr_html
from job_agent.collectors.vseti import VsetiCollector, parse_vseti_html

FIXTURES = Path(__file__).parent / "fixtures"
VSETI_HTML = FIXTURES / "vseti_jobs.html"
HABR_HTML = FIXTURES / "habr_vacancies.html"
GETMATCH_JSON = FIXTURES / "getmatch_vacancies.json"


def _vseti_html() -> str:
    return VSETI_HTML.read_text(encoding="utf-8")


def _habr_html() -> str:
    return HABR_HTML.read_text(encoding="utf-8")


def _getmatch_json() -> str:
    return GETMATCH_JSON.read_text(encoding="utf-8")


# --- vseti -------------------------------------------------------------------


def test_vseti_parse_extracts_cards_and_skips_empty() -> None:
    posts = parse_vseti_html(_vseti_html())

    # пустая карточка-ссылка (203) отброшена
    assert len(posts) == 2

    first = posts[0]
    assert first.source == "vseti"
    assert first.url == "https://www.vseti.app/vakansii/201"
    assert first.date is None  # листинг свежий, дата в карточке не указана
    # весь текст карточки — материал для нормализации
    assert "Product Manager" in first.raw_text
    assert "AlphaScale" in first.raw_text
    assert "300000" in first.raw_text
    assert "retention" in first.raw_text

    # относительная ссылка достраивается до абсолютной
    assert posts[1].url == "https://vseti.app/vakansii/202"
    assert "Head of AI" in posts[1].raw_text


def test_vseti_fetch_returns_all_when_no_dates() -> None:
    collector = VsetiCollector(fetcher=lambda _u: _vseti_html())
    # дата карточек None → since не отсекает (листинг всегда свежий)
    posts = collector.fetch(datetime(2024, 6, 1, tzinfo=UTC))
    assert {p.url for p in posts} == {
        "https://www.vseti.app/vakansii/201",
        "https://vseti.app/vakansii/202",
    }


def test_vseti_garbage_html_yields_nothing() -> None:
    assert parse_vseti_html("<html><body>no cards here</body></html>") == []


# --- habr --------------------------------------------------------------------


def test_habr_parse_extracts_cards_and_skips_empty() -> None:
    posts = parse_habr_html(_habr_html())

    assert len(posts) == 2  # пустая карточка отброшена
    first = posts[0]
    assert first.source == "habr"
    assert first.url == "https://career.habr.com/vacancies/100200"
    assert first.date == datetime(2026, 6, 28, 23, 26, 11, tzinfo=first.date.tzinfo)
    assert "Product Manager" in first.raw_text
    assert "AlphaScale" in first.raw_text
    assert "300000" in first.raw_text
    assert posts[1].url == "https://career.habr.com/vacancies/100201"


def test_habr_fetch_filters_by_since() -> None:
    collector = HabrCollector(fetcher=lambda _u: _habr_html())
    posts = collector.fetch(datetime(2024, 6, 1, tzinfo=UTC))
    # карточка от 2024-05-01 отсечена по дате
    assert {p.url for p in posts} == {"https://career.habr.com/vacancies/100200"}


def test_habr_garbage_html_yields_nothing() -> None:
    assert parse_habr_html("<html><body>no cards</body></html>") == []


# --- getmatch ----------------------------------------------------------------


def test_getmatch_parse_extracts_fields_and_skips_titleless() -> None:
    posts = parse_getmatch_json(_getmatch_json())

    # запись без заголовка (304) пропущена
    assert len(posts) == 3

    first = posts[0]
    assert first.source == "getmatch"
    assert first.url == "https://getmatch.ru/vacancies/301-senior-product-manager"
    assert first.date == datetime(2024, 6, 26, 10, 0, tzinfo=UTC)
    assert "Senior Product Manager" in first.raw_text
    assert "MatchScale" in first.raw_text
    assert "350000" in first.raw_text  # из salary_from
    assert "метриками" in first.raw_text

    # компания строкой (а не объектом) тоже поддержана
    third = posts[2]
    assert "LegacyOrg" in third.raw_text
    # явное поле salary имеет приоритет
    second = posts[1]
    assert "300000–600000 ₽" in second.raw_text


def test_getmatch_fetch_filters_by_since() -> None:
    collector = GetmatchCollector(fetcher=lambda _u: _getmatch_json())

    posts = collector.fetch(datetime(2024, 6, 1, tzinfo=UTC))
    # архивная запись 303 (10 апреля) отсечена
    assert {p.url for p in posts} == {
        "https://getmatch.ru/vacancies/301-senior-product-manager",
        "https://getmatch.ru/vacancies/302-ai-product-lead",
    }


def test_getmatch_garbage_json_yields_nothing() -> None:
    assert parse_getmatch_json("not json at all") == []
    assert parse_getmatch_json('{"unexpected": 42}') == []
    assert parse_getmatch_json("[]") == []


def test_getmatch_bare_list_supported() -> None:
    posts = parse_getmatch_json('[{"title": "Dev", "id": 9}]')
    assert len(posts) == 1
    assert posts[0].url == "https://getmatch.ru/vacancies/9"
