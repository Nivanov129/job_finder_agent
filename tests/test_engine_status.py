"""Юнит-тесты детекции движков и `.env`-стора — без сети/процессов.

Внешние границы (поиск бинаря, версия, HTTP к Ollama) инъектируются фейками.
"""

from __future__ import annotations

from pathlib import Path

from webui.engine_status import (
    claude_status,
    codex_status,
    engine_statuses,
    ollama_status,
)
from webui.env_store import merge_env, parse_env


def _which(present: set[str]):
    return lambda tool: f"/usr/bin/{tool}" if tool in present else None


def _run_ok(argv: list[str]) -> str:
    return f"{argv[0]} 1.0.0"


def test_claude_installed_and_authorized_by_token(tmp_path: Path) -> None:
    st = claude_status(
        which=_which({"claude"}),
        run=_run_ok,
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        creds_path=tmp_path / "nope.json",
    )
    assert st.installed is True and st.authorized is True
    assert st.billing == "subscription"


def test_claude_installed_authorized_by_creds_file(tmp_path: Path) -> None:
    creds = tmp_path / ".credentials.json"
    creds.write_text("{}", encoding="utf-8")
    st = claude_status(which=_which({"claude"}), run=_run_ok, env={}, creds_path=creds)
    assert st.authorized is True


def test_claude_not_installed(tmp_path: Path) -> None:
    st = claude_status(
        which=_which(set()), run=_run_ok, env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        creds_path=tmp_path / "x",
    )
    assert st.installed is False and st.authorized is False


def test_codex_authorized_by_env_key(tmp_path: Path) -> None:
    st = codex_status(
        which=_which({"codex"}), run=_run_ok, env={"OPENAI_API_KEY": "k"},
        auth_path=tmp_path / "x",
    )
    assert st.installed is True and st.authorized is True


def test_ollama_reachable_lists_models() -> None:
    def http_get(url: str) -> dict:
        assert url.endswith("/api/tags")
        return {"models": [{"name": "llama3.1:70b"}]}

    st = ollama_status("http://ollama:11434", http_get=http_get)
    assert st.authorized is True and st.installed is None
    assert "llama3.1:70b" in st.detail
    assert st.billing == "free"


def test_ollama_unreachable() -> None:
    def http_get(url: str) -> dict:
        raise ConnectionError("nope")

    st = ollama_status("http://ollama:11434", http_get=http_get)
    assert st.authorized is False


def test_engine_statuses_order_and_keys() -> None:
    states = engine_statuses(
        env={}, ollama_url="", has_api_key=False,
        which=_which({"claude", "codex"}), run=_run_ok,
        http_get=lambda url: {"models": []},
    )
    assert [s.key for s in states] == ["claude", "codex", "ollama", "api_key"]


def test_parse_and_merge_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=1\n# comment\nBAR='two'\n", encoding="utf-8")
    assert parse_env(env) == {"FOO": "1", "BAR": "two"}

    merge_env(env, {"OPENAI_API_KEY": "k", "FOO": None})  # FOO удаляется
    values = parse_env(env)
    assert values["OPENAI_API_KEY"] == "k"
    assert values["BAR"] == "two"  # чужой ключ сохранён
    assert "FOO" not in values


def test_parse_env_missing_file(tmp_path: Path) -> None:
    assert parse_env(tmp_path / "absent.env") == {}
