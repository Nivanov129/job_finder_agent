"""Тесты инвестигатора контактов: парс строгого JSON + гейты, без сети."""

from __future__ import annotations

import json

from job_agent.enrich.investigator import (
    investigate_contacts,
    parse_investigation,
    render_prompt,
)
from job_agent.models import Vacancy


class FakeEngine:
    """Фейк-движок: возвращает заранее заданный ответ, помнит web_search."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.web_search_used: bool | None = None

    def complete(self, prompt: str, *, web_search: bool = False) -> str:
        self.web_search_used = web_search
        return self.reply


_GOOD = json.dumps(
    {
        "contacts": [
            {
                "name": "Анна Рекрутер",
                "role": "Talent Acquisition",
                "contact_route": "@anna_hr",
                "link": "https://t.me/anna_hr",
                "confidence": 80,
                "evidence_grade": "cross-source",
                "rationale": "профиль найма в двух источниках",
            }
        ],
        "evidence_checked": ["telegram — найден контакт", "linkedin — пусто"],
        "next_actions": ["написать @anna_hr"],
    }
)


def _vac() -> Vacancy:
    return Vacancy(title="Product Manager", company="Avito")


def test_parse_investigation_ok():
    inv = parse_investigation(_GOOD)
    assert inv is not None
    assert inv.contacts[0].name == "Анна Рекрутер"
    assert inv.contacts[0].confidence == 80
    assert inv.contacts[0].evidence_grade == "cross-source"
    assert "telegram — найден контакт" in inv.evidence_checked


def test_parse_investigation_garbage_is_none():
    assert parse_investigation("не json вообще") is None


def test_investigate_disabled_returns_none():
    eng = FakeEngine(_GOOD)
    assert investigate_contacts(
        _vac(), eng, track_name="PM", enable_investigator=False
    ) is None
    assert eng.web_search_used is None  # движок не звали


def test_investigate_without_company_returns_none():
    eng = FakeEngine(_GOOD)
    vac = Vacancy(title="PM", company=None)
    assert investigate_contacts(
        vac, eng, track_name="PM", enable_investigator=True
    ) is None


def test_investigate_uses_web_search_and_parses():
    eng = FakeEngine(_GOOD)
    inv = investigate_contacts(
        _vac(), eng, track_name="PM", enable_investigator=True
    )
    assert inv is not None and inv.contacts[0].confidence == 80
    assert eng.web_search_used is True  # инвестигатору нужен web


def test_render_prompt_substitutes_fields():
    p = render_prompt(_vac(), track_name="PM", region="Москва")
    assert "Product Manager" in p
    assert "Avito" in p
    assert "Москва" in p
    assert "{{role}}" not in p
