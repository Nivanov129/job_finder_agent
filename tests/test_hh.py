"""Тесты hh-фетчера вакансий (webui/hh.py) — без сети, транспорт фейковый."""

from __future__ import annotations

from typing import Any

import pytest
from webui.hh import (
    build_vacancy_text,
    fetch_hh_vacancy_text,
    parse_hh_vacancy_id,
)


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://hh.ru/vacancy/12345678", "12345678"),
        ("https://spb.hh.ru/vacancy/999?from=search", "999"),
        ("https://hh.kz/vacancy/555", "555"),
        ("hh.ru/vacancy/42", "42"),  # без схемы
        ("https://career.habr.com/vacancies/777", None),  # другой агрегатор
        ("https://hh.ru/search/vacancy?text=product", None),  # список, не вакансия
        ("https://myhh.ru/vacancy/1", None),  # не настоящий hh-хост
        ("не ссылка вовсе", None),
    ],
)
def test_parse_hh_vacancy_id(url: str, expected: str | None) -> None:
    assert parse_hh_vacancy_id(url) == expected


def test_build_vacancy_text_collects_fields_and_strips_html() -> None:
    data: dict[str, Any] = {
        "name": "Product Manager",
        "employer": {"name": "Acme"},
        "description": "<p>Ищем <b>лидера</b> &amp; продакта</p><script>x()</script>",
        "key_skills": [{"name": "Roadmap"}, {"name": "A/B"}],
    }
    text = build_vacancy_text(data)
    assert "Product Manager" in text
    assert "Компания: Acme" in text
    assert "Ищем лидера & продакта" in text  # теги убраны, сущности распакованы
    assert "<" not in text and "script" not in text  # скрипт вырезан
    assert "Ключевые навыки: Roadmap, A/B" in text


def test_build_vacancy_text_tolerates_missing_fields() -> None:
    assert build_vacancy_text({}) == ""
    assert build_vacancy_text({"name": "QA", "employer": None}) == "QA"


def test_fetch_uses_api_for_hh_link() -> None:
    calls: list[str] = []

    def fake(url: str, headers: dict[str, str]) -> dict[str, Any]:
        calls.append(url)
        assert "User-Agent" in headers  # hh требует внятный UA
        return {"name": "Data PM", "employer": {"name": "deeplay"}, "description": "текст"}

    text = fetch_hh_vacancy_text("https://hh.ru/vacancy/100", transport=fake)
    assert text is not None
    assert "Data PM" in text and "deeplay" in text
    assert calls == ["https://api.hh.ru/vacancies/100"]


def test_fetch_returns_none_for_non_hh_without_calling_transport() -> None:
    def fake(url: str, headers: dict[str, str]) -> dict[str, Any]:  # не должен вызваться
        raise AssertionError("транспорт не должен дёргаться для не-hh ссылки")

    assert fetch_hh_vacancy_text("https://career.habr.com/vacancies/1", transport=fake) is None


def test_fetch_swallows_transport_errors() -> None:
    def boom(url: str, headers: dict[str, str]) -> dict[str, Any]:
        raise RuntimeError("403 Forbidden")

    # сетевой сбой/403 → None, чтобы вызывающий упал на обычный загрузчик
    assert fetch_hh_vacancy_text("https://hh.ru/vacancy/7", transport=boom) is None


def test_fetch_returns_none_on_empty_payload() -> None:
    assert fetch_hh_vacancy_text("https://hh.ru/vacancy/7", transport=lambda u, h: {}) is None
