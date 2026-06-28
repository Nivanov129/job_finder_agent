"""Юнит-тесты AI-классификации каналов — фейк-движок, без сети/Telethon."""

from __future__ import annotations

from webui.telegram_login import (
    build_classify_prompt,
    classify_channels,
    parse_channel_ids,
)


class _FakeEngine:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompt = ""

    def complete(self, prompt: str, *, web_search: bool = False) -> str:
        self.prompt = prompt
        return self.answer


_CHANNELS = [
    {"id": "jobs_ru", "title": "Вакансии IT", "description": "Работа в IT"},
    {"id": "memes", "title": "Мемы", "description": "юмор"},
    {"id": "product_jobs", "title": "Product Jobs", "description": ""},
]


def test_build_prompt_lists_channels() -> None:
    p = build_classify_prompt(_CHANNELS)
    assert "id=jobs_ru" in p and "Вакансии IT" in p
    assert "id=memes" in p
    assert "JSON" in p


def test_parse_channel_ids_plain() -> None:
    assert parse_channel_ids('["jobs_ru", "product_jobs"]') == ["jobs_ru", "product_jobs"]


def test_parse_channel_ids_with_preamble_and_fence() -> None:
    text = 'Вот ответ:\n```json\n["a", 2, "b"]\n```\nготово'
    assert parse_channel_ids(text) == ["a", "2", "b"]


def test_parse_channel_ids_garbage_empty() -> None:
    assert parse_channel_ids("не знаю") == []


def test_classify_channels_returns_job_ids() -> None:
    engine = _FakeEngine('["jobs_ru", "product_jobs"]')
    result = classify_channels(engine, _CHANNELS)
    assert result == {"jobs_ru", "product_jobs"}
    assert "Вакансии IT" in engine.prompt  # промт реально собран из каналов


def test_classify_channels_empty_input_no_engine_call() -> None:
    engine = _FakeEngine("[]")
    assert classify_channels(engine, []) == set()
    assert engine.prompt == ""  # движок не звался
