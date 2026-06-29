"""Юнит-тесты детекции движков и `.env`-стора — без сети/процессов.

Внешние границы (поиск бинаря, версия, HTTP к Ollama) инъектируются фейками.
"""

from __future__ import annotations

from pathlib import Path

from webui.engine_status import (
    claude_status,
    codex_status,
    engine_statuses,
    ollama_models,
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


def test_ollama_local_reachable_lists_models() -> None:
    def http_get(url: str, headers: dict) -> dict:
        assert url.endswith("/v1/models")  # OpenAI-совместимый эндпоинт
        assert "authorization" not in headers  # свой сервер — без ключа
        return {"data": [{"id": "llama3.1:70b"}]}

    st = ollama_status("http://ollama:11434", http_get=http_get)
    assert st.authorized is True and st.installed is None
    assert "llama3.1:70b" in st.detail
    assert st.label == "Ollama"


def test_ollama_cloud_needs_key() -> None:
    called = False

    def http_get(url: str, headers: dict) -> dict:
        nonlocal called
        called = True
        return {"models": []}

    st = ollama_status("", api_key=None, http_get=http_get)  # облако без ключа
    assert st.authorized is False
    assert st.label == "Ollama Cloud"
    assert "OLLAMA_API_KEY" in st.detail
    assert called is False  # без ключа в сеть не ходим


def test_ollama_cloud_status_sends_bearer_but_cant_verify_key() -> None:
    def http_get(url: str, headers: dict) -> dict:
        assert url == "https://ollama.com/v1/models"
        assert headers["authorization"] == "Bearer sk-cloud"
        return {"data": [{"id": "gpt-oss:120b"}]}

    st = ollama_status("", api_key="sk-cloud", http_get=http_get)
    # /v1/models публичный и не валидирует ключ → честно «неизвестно» (не True).
    assert st.authorized is None
    assert "ключ задан" in st.detail and "моделей: 1" in st.detail


def test_ollama_unreachable() -> None:
    def http_get(url: str, headers: dict) -> dict:
        raise ConnectionError("nope")

    st = ollama_status("http://ollama:11434", http_get=http_get)
    assert st.authorized is False


def test_ollama_models_helper_returns_ids() -> None:
    def http_get(url: str, headers: dict) -> dict:
        assert url == "https://ollama.com/v1/models"
        assert headers["authorization"] == "Bearer k"
        return {"data": [{"id": "a"}, {"id": "b"}, {"other": "x"}]}

    # OpenAI-формат /v1/models: id как есть, без :cloud.
    assert ollama_models("", api_key="k", http_get=http_get) == ["a", "b"]


def test_ollama_models_helper_swallows_errors() -> None:
    def http_get(url: str, headers: dict) -> dict:
        raise ConnectionError("nope")

    assert ollama_models("http://x:11434", http_get=http_get) == []


def test_engine_statuses_threads_ollama_key() -> None:
    seen: dict[str, dict] = {}

    def http_get(url: str, headers: dict) -> dict:
        seen["headers"] = headers
        return {"models": []}

    states = engine_statuses(
        env={"OLLAMA_API_KEY": "sk"}, ollama_url="",
        which=_which({"codex"}), run=_run_ok,
        http_get=http_get,
    )
    assert [s.key for s in states] == ["codex", "ollama"]
    assert seen["headers"]["authorization"] == "Bearer sk"


def test_recommend_first_prioritizes_task_models() -> None:
    from webui.engine_status import recommend_first

    out = recommend_first(["tinyllama:1b", "gpt-oss:120b", "deepseek-v3.1:671b"])
    # подходящие под задачу (gpt-oss, deepseek) — впереди прочего
    assert out[0] == "gpt-oss:120b"
    assert out[1] == "deepseek-v3.1:671b"
    assert out[-1] == "tinyllama:1b"


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
