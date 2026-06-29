"""Тесты интерфейса AI-движка: фейк и фабрика (без сети)."""

from __future__ import annotations

import pytest

from job_agent.config import Config, ConfigError, Track
from job_agent.engines import KNOWN_ENGINES, Engine, FakeEngine, make_engine


def _config(engine: str) -> Config:
    return Config(
        version=1,
        tracks=[Track(id="t1", name="Трек", resume_path="./r.pdf")],
        scoring_engine=engine,
        output_mode="xlsx",
    )


def test_fake_is_engine_and_returns_canned_response() -> None:
    fake = FakeEngine("ответ")
    assert isinstance(fake, Engine)
    assert fake.complete("промт") == "ответ"


def test_fake_records_calls_and_web_search_flag() -> None:
    fake = FakeEngine("ok")
    fake.complete("a")
    fake.complete("b", web_search=True)

    assert fake.call_count == 2
    assert fake.calls == [("a", False), ("b", True)]
    assert fake.last_prompt == "b"


def test_fake_responses_queue_in_order() -> None:
    fake = FakeEngine(responses=["один", "два"])
    assert fake.complete("x") == "один"
    assert fake.complete("y") == "два"


def test_fake_exhausted_queue_raises() -> None:
    fake = FakeEngine(responses=["единственный"])
    fake.complete("x")
    with pytest.raises(AssertionError):
        fake.complete("y")


def test_fake_callable_response_sees_prompt() -> None:
    fake = FakeEngine(lambda prompt: prompt.upper())
    assert fake.complete("привет") == "ПРИВЕТ"


def test_make_engine_override_takes_priority() -> None:
    fake = FakeEngine("inj")
    # override возвращается даже при «реальном» scoring_engine — без импорта адаптера
    assert make_engine(_config("cli"), override=fake) is fake


def test_make_engine_unknown_raises_config_error() -> None:
    cfg = _config("cli")
    cfg.scoring_engine = "bogus"
    with pytest.raises(ConfigError) as exc:
        make_engine(cfg)
    assert "bogus" in str(exc.value)


def test_known_engines_match_schema_enum() -> None:
    assert KNOWN_ENGINES == ("cli", "api_key", "ollama", "openrouter")


def test_make_engine_openrouter_reads_env_key(monkeypatch) -> None:
    from job_agent.engines.api_key import ApiKeyEngine

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    engine = make_engine(_config("openrouter"))
    assert isinstance(engine, ApiKeyEngine) and engine.provider == "openrouter"


def test_make_engine_openrouter_without_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        make_engine(_config("openrouter"))
