"""Тесты конкретных адаптеров движков (cli / api_key / ollama) на фейках транспорта.

Ни один тест не выходит в сеть и не запускает процессы: вместо реального
subprocess/httpx инъектируется фейк-runner/transport.
"""

from __future__ import annotations

import pytest

from job_agent.config import Config, ConfigError, Track
from job_agent.engines import Engine, make_engine
from job_agent.engines.api_key import (
    ApiKeyEngine,
    detect_provider,
)
from job_agent.engines.api_key import (
    build_request as api_build_request,
)
from job_agent.engines.api_key import (
    parse_response as api_parse_response,
)
from job_agent.engines.cli import CliEngine, build_argv
from job_agent.engines.ollama import (
    OllamaEngine,
)
from job_agent.engines.ollama import (
    build_request as ollama_build_request,
)
from job_agent.engines.ollama import (
    parse_response as ollama_parse_response,
)


def _config(engine: str, **kw: object) -> Config:
    return Config(
        version=1,
        tracks=[Track(id="t1", name="Трек", resume_path="./r.pdf")],
        scoring_engine=engine,
        output_mode="xlsx",
        **kw,  # type: ignore[arg-type]
    )


# --- CLI ---------------------------------------------------------------------


def test_cli_build_argv_per_tool() -> None:
    assert build_argv("claude", "P") == ["claude", "-p", "P"]
    # codex: вне git-репо + без цвета; чистый ответ — в файл --output-last-message
    assert build_argv("codex", "P") == [
        "codex", "exec", "--skip-git-repo-check", "--color", "never", "P",
    ]
    assert build_argv("codex", "P", output_file="/tmp/o.txt") == [
        "codex", "exec", "--skip-git-repo-check", "--color", "never",
        "--output-last-message", "/tmp/o.txt", "P",
    ]


def test_codex_complete_reads_output_file() -> None:
    # codex: чистый ответ берётся из файла --output-last-message, не из stdout
    # (stdout = баннер + эхо промта со скобками схемы).
    def runner(argv: list[str]) -> str:
        path = argv[argv.index("--output-last-message") + 1]
        with open(path, "w", encoding="utf-8") as f:
            f.write('[{"title": "X"}]\n')
        return "OpenAI Codex banner\nuser\n[schema]\ncodex\nignored\ntokens used\n42"

    assert CliEngine("codex", runner=runner).complete("p") == '[{"title": "X"}]'


def test_cli_build_argv_unknown_tool_raises() -> None:
    with pytest.raises(ConfigError):
        build_argv("bogus", "P")


def test_cli_engine_runs_through_injected_runner() -> None:
    seen: list[list[str]] = []

    def runner(argv: list[str]) -> str:
        seen.append(argv)
        return "  ответ модели \n"

    engine = CliEngine("claude", runner=runner)
    assert isinstance(engine, Engine)
    assert engine.complete("привет") == "ответ модели"
    assert seen == [["claude", "-p", "привет"]]


def test_cli_engine_rejects_unknown_tool() -> None:
    with pytest.raises(ConfigError):
        CliEngine("bogus", runner=lambda argv: "")


def test_cli_from_config_requires_cli_tool() -> None:
    with pytest.raises(ConfigError):
        CliEngine.from_config(_config("cli"))  # cli_tool не задан


def test_make_engine_builds_cli_with_runner_via_subclass() -> None:
    engine = CliEngine.from_config(_config("cli", cli_tool="codex"), runner=lambda a: "ok")
    assert engine.complete("x") == "ok"


# --- API key -----------------------------------------------------------------


def test_detect_provider_defaults_to_anthropic() -> None:
    assert detect_provider(None) == "anthropic"
    assert detect_provider("https://api.anthropic.com") == "anthropic"
    assert detect_provider("https://api.openai.com/v1") == "openai"


def test_anthropic_request_shape_and_secret_in_header() -> None:
    url, headers, body = api_build_request(
        "anthropic", "https://api.anthropic.com", "SECRET", "m", "P", web_search=True
    )
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "SECRET"
    assert body["messages"] == [{"role": "user", "content": "P"}]
    assert body["tools"][0]["name"] == "web_search"


def test_openai_request_shape() -> None:
    url, headers, body = api_build_request(
        "openai", "https://api.openai.com", "SECRET", "m", "P"
    )
    assert url == "https://api.openai.com/v1/chat/completions"
    assert headers["authorization"] == "Bearer SECRET"
    assert "tools" not in body


def test_api_parse_response_per_provider() -> None:
    anthropic_data = {
        "content": [
            {"type": "text", "text": "часть1 "},
            {"type": "tool_use", "id": "x"},
            {"type": "text", "text": "часть2"},
        ]
    }
    assert api_parse_response("anthropic", anthropic_data) == "часть1 часть2"
    openai_data = {"choices": [{"message": {"content": "  ответ "}}]}
    assert api_parse_response("openai", openai_data) == "ответ"
    assert api_parse_response("openai", {"choices": []}) == ""


def test_api_engine_uses_transport_and_hides_secret_in_repr() -> None:
    captured: dict[str, object] = {}

    def transport(url: str, headers: dict[str, str], body: dict) -> dict:
        captured["url"] = url
        captured["headers"] = headers
        return {"content": [{"type": "text", "text": "готово"}]}

    engine = ApiKeyEngine("TOPSECRET", transport=transport)
    assert engine.provider == "anthropic"
    assert engine.complete("вопрос") == "готово"
    assert captured["headers"]["x-api-key"] == "TOPSECRET"  # type: ignore[index]
    assert "TOPSECRET" not in repr(engine)


def test_api_engine_openai_via_base_url() -> None:
    def transport(url: str, headers: dict[str, str], body: dict) -> dict:
        return {"choices": [{"message": {"content": "oa"}}]}

    engine = ApiKeyEngine(
        "k", base_url="https://api.openai.com", transport=transport
    )
    assert engine.provider == "openai"
    assert engine.complete("x") == "oa"


def test_api_engine_requires_key() -> None:
    with pytest.raises(ConfigError):
        ApiKeyEngine("")


def test_api_from_config_requires_key() -> None:
    with pytest.raises(ConfigError):
        ApiKeyEngine.from_config(_config("api_key"))


# --- Ollama ------------------------------------------------------------------


def test_ollama_request_shape_no_stream() -> None:
    url, headers, body = ollama_build_request("http://localhost:11434", "llama3.1", "P")
    assert url == "http://localhost:11434/api/chat"
    assert body["stream"] is False
    assert body["model"] == "llama3.1"
    assert body["messages"] == [{"role": "user", "content": "P"}]
    # Локальный сервер — без заголовка авторизации.
    assert "authorization" not in headers


def test_ollama_cloud_adds_bearer_auth() -> None:
    _, headers, _ = ollama_build_request(
        "https://ollama.com", "gpt-oss:120b", "P", api_key="sk-cloud"
    )
    assert headers["authorization"] == "Bearer sk-cloud"


def test_ollama_from_config_reads_cloud_key_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "sk-from-env")
    captured: dict[str, str] = {}

    def transport(url: str, headers: dict[str, str], body: dict) -> dict:
        captured.update(headers)
        return {"message": {"content": "ok"}}

    engine = OllamaEngine.from_config(
        _config("ollama", ollama_model="gpt-oss:120b"), transport=transport
    )
    engine.complete("x")
    assert captured["authorization"] == "Bearer sk-from-env"


def test_ollama_defaults_to_cloud_host(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    captured: dict[str, str] = {}

    def transport(url: str, headers: dict[str, str], body: dict) -> dict:
        captured["url"] = url
        return {"message": {"content": "ok"}}

    OllamaEngine("gpt-oss:120b", transport=transport).complete("x")
    assert captured["url"] == "https://ollama.com/api/chat"


def test_ollama_parse_response() -> None:
    assert ollama_parse_response({"message": {"content": " ответ "}}) == "ответ"
    assert ollama_parse_response({}) == ""


def test_ollama_engine_uses_transport_and_ignores_web_search() -> None:
    def transport(url: str, headers: dict[str, str], body: dict) -> dict:
        return {"message": {"content": "локально"}}

    engine = OllamaEngine("llama3.1:70b", transport=transport)
    assert engine.complete("x", web_search=True) == "локально"


def test_ollama_engine_requires_model() -> None:
    with pytest.raises(ConfigError):
        OllamaEngine("")


def test_ollama_from_config_requires_model() -> None:
    with pytest.raises(ConfigError):
        OllamaEngine.from_config(_config("ollama"))


# --- Фабрика строит реальные адаптеры (без сети) -----------------------------


def test_make_engine_builds_each_adapter() -> None:
    assert isinstance(make_engine(_config("cli", cli_tool="claude")), CliEngine)
    assert isinstance(
        make_engine(_config("api_key", api_key="k")), ApiKeyEngine
    )
    assert isinstance(
        make_engine(_config("ollama", ollama_model="llama3.1")), OllamaEngine
    )
