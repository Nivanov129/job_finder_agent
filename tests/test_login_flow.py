"""Юнит-тесты server-driven входа — фейк-процесс, без реального CLI/сети."""

from __future__ import annotations

import re
from pathlib import Path

from webui.env_store import parse_env
from webui.login_flow import URL_RE, LoginManager, LoginProcess, LoginResult


class _FakeClaude:
    """Имитирует claude setup-token: ссылка → код → токен в результате."""

    def __init__(self) -> None:
        self._code: str | None = None

    def read(self, pattern: re.Pattern[str], timeout: float) -> str | None:
        return "https://claude.ai/oauth/authorize?code=1" if pattern is URL_RE else None

    def submit_code(self, code: str) -> None:
        self._code = code

    def result(self, timeout: float) -> LoginResult:
        if self._code:
            return LoginResult(True, "токен получен", token="sk-ant-oat01-FAKE")
        return LoginResult(False, "код не введён")

    def stop(self) -> None:
        pass


class _FakeCodex:
    """Имитирует codex device-auth: ссылка + одноразовый код, завершение по браузеру."""

    def read(self, pattern: re.Pattern[str], timeout: float) -> str | None:
        return "https://auth.openai.com/codex/device" if pattern is URL_RE else "CVBJ-2XUDK"

    def submit_code(self, code: str) -> None:  # codex код в нашу форму не вводит
        pass

    def result(self, timeout: float) -> LoginResult:
        return LoginResult(True, "вход выполнен")

    def stop(self) -> None:
        pass


def _spawn(engine: str) -> LoginProcess:
    return _FakeClaude() if engine == "claude" else _FakeCodex()


def test_claude_start_returns_url_and_code_mode(tmp_path: Path) -> None:
    mgr = LoginManager(tmp_path / ".env", spawn=_spawn)
    res = mgr.start("claude")
    assert res["ok"] is True
    assert res["mode"] == "code"
    assert str(res["url"]).startswith("https://")


def test_claude_submit_writes_token_to_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    mgr = LoginManager(env, spawn=_spawn)
    mgr.start("claude")
    res = mgr.submit("claude", "the-code")
    assert res["ok"] is True
    assert parse_env(env)["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-FAKE"


def test_codex_device_mode_shows_code_no_token(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    mgr = LoginManager(env, spawn=_spawn)
    started = mgr.start("codex")
    assert started["mode"] == "device"
    assert started["code"] == "CVBJ-2XUDK"  # одноразовый код для ввода в браузере
    assert "auth.openai.com" in str(started["url"])
    res = mgr.submit("codex")  # без кода — ждём подтверждения браузера
    assert res["ok"] is True
    # codex сам пишет auth.json, токена в .env нет
    assert not env.exists() or "CLAUDE_CODE_OAUTH_TOKEN" not in parse_env(env)


def test_submit_failure_writes_no_token(tmp_path: Path) -> None:
    """Неверный/истёкший код: result(ok=False) → токен в .env не пишется."""

    class _FailClaude(_FakeClaude):
        def result(self, timeout: float) -> LoginResult:
            return LoginResult(False, "код неверный или истёк")

    env = tmp_path / ".env"
    mgr = LoginManager(env, spawn=lambda e: _FailClaude())
    mgr.start("claude")
    res = mgr.submit("claude", "bad-code")
    assert res["ok"] is False
    assert not env.exists() or "CLAUDE_CODE_OAUTH_TOKEN" not in parse_env(env)


def test_submit_without_start_errors(tmp_path: Path) -> None:
    mgr = LoginManager(tmp_path / ".env", spawn=_spawn)
    res = mgr.submit("claude", "x")
    assert res["ok"] is False
    assert "не начат" in str(res["message"])


def test_unsupported_engine_errors(tmp_path: Path) -> None:
    mgr = LoginManager(tmp_path / ".env", spawn=_spawn)
    res = mgr.start("ollama")
    assert res["ok"] is False


def test_start_replaces_prior_session(tmp_path: Path) -> None:
    stopped: list[str] = []

    class _Tracking(_FakeClaude):
        def stop(self) -> None:
            stopped.append("x")

    mgr = LoginManager(tmp_path / ".env", spawn=lambda e: _Tracking())
    mgr.start("claude")
    mgr.start("claude")  # повторный старт закрывает прежнюю сессию
    assert stopped  # прежний процесс остановлен
