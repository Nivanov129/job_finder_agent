"""Тесты подключения бот-уведомлений (webui/bot_connect.py) — без сети."""

from __future__ import annotations

from typing import Any

from webui.bot_connect import (
    parse_chat_id_from_updates,
    resolve_owner_chat_id,
    send_test_message,
)


def _update(chat_id: int, chat_type: str = "private") -> dict[str, Any]:
    return {"message": {"chat": {"id": chat_id, "type": chat_type}}}


def test_parse_picks_last_private_chat_id() -> None:
    data = {"ok": True, "result": [_update(111), _update(222)]}
    assert parse_chat_id_from_updates(data) == 222  # последний — самый свежий


def test_parse_ignores_groups_and_channels() -> None:
    data = {"ok": True, "result": [_update(-100, "group"), _update(-1, "channel")]}
    assert parse_chat_id_from_updates(data) is None


def test_parse_handles_edited_message() -> None:
    data = {"ok": True, "result": [{"edited_message": {"chat": {"id": 7, "type": "private"}}}]}
    assert parse_chat_id_from_updates(data) == 7


def test_parse_none_on_empty_or_not_ok() -> None:
    assert parse_chat_id_from_updates({"ok": False, "result": []}) is None
    assert parse_chat_id_from_updates({"ok": True, "result": []}) is None
    assert parse_chat_id_from_updates({}) is None


def test_resolve_uses_http_get_and_parses() -> None:
    calls: list[str] = []

    def fake_get(url: str) -> dict[str, Any]:
        calls.append(url)
        return {"ok": True, "result": [_update(555)]}

    assert resolve_owner_chat_id("TOK", http_get=fake_get) == 555
    assert calls == ["https://api.telegram.org/botTOK/getUpdates"]


def test_resolve_swallows_errors() -> None:
    def boom(url: str) -> dict[str, Any]:
        raise RuntimeError("сеть")

    assert resolve_owner_chat_id("TOK", http_get=boom) is None


def test_send_test_message_reports_ok() -> None:
    sent: list[dict[str, Any]] = []

    def fake_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        sent.append(payload)
        return {"ok": True}

    assert send_test_message("TOK", 42, "привет", http_post=fake_post) is True
    assert sent == [{"chat_id": 42, "text": "привет"}]


def test_send_test_message_false_on_reject_or_error() -> None:
    assert send_test_message("T", 1, "x", http_post=lambda u, p: {"ok": False}) is False

    def boom(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("403")

    assert send_test_message("T", 1, "x", http_post=boom) is False
