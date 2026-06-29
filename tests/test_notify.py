"""Тесты бот-уведомлений о новых вакансиях (webui/notify.py) — без сети.

Логику бриджа (гейт по токену/chat_id, проброс полей конфига) тестируем,
подменяя `send_digest` — сам дайджест покрыт в test_bot.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from webui import notify
from webui.bot_connect import BOT_TOKEN_ENV

from job_agent.config import Config


def _config(**over: Any) -> Config:
    data: dict[str, Any] = {
        "version": 1,
        "tracks": [{"id": "t", "name": "T", "resume_path": "r.pdf"}],
        "scoring_engine": "openrouter",
        "output_mode": "table",
    }
    data.update(over)
    return Config(**data)


def test_noop_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BOT_TOKEN_ENV, raising=False)
    assert notify.notify_new_vacancies(_config(owner_chat_id=42), ["r"]) == 0


def test_noop_without_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BOT_TOKEN_ENV, "TOK")
    assert notify.notify_new_vacancies(_config(owner_chat_id=None), ["r"]) == 0


def test_noop_without_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BOT_TOKEN_ENV, "TOK")
    assert notify.notify_new_vacancies(_config(owner_chat_id=42), []) == 0


def test_sends_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BOT_TOKEN_ENV, "TOK")
    captured: dict[str, Any] = {}

    def fake_send_digest(results, transport, chat_id, **kw):  # noqa: ANN001
        captured["results"] = list(results)
        captured["chat_id"] = chat_id
        captured["kw"] = kw
        return ["card1", "card2"]

    monkeypatch.setattr(notify, "send_digest", fake_send_digest)

    sentinel = object()
    n = notify.notify_new_vacancies(
        _config(owner_chat_id=999, cover_letter_threshold=80), [sentinel]
    )
    assert n == 2
    assert captured["chat_id"] == 999
    assert captured["results"] == [sentinel]
    assert captured["kw"]["cover_letter_threshold"] == 80
    assert captured["kw"]["is_single_track"] is True  # один трек
