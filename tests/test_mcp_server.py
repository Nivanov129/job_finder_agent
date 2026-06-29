"""Тесты доменных функций MCP-сервера (job_agent/mcp_server.py) — без сети.

Тяжёлые границы (пайплайн, движок, web-поиск, find_contacts) инъектируются или
подменяются; проверяем оркестрацию и формы данных.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from job_agent import mcp_server


def _write_config(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "tracks": [{"id": "t", "name": "T", "resume_path": "r.pdf"}],
                "scoring_engine": "openrouter",
                "output_mode": "table",
                "backfill_days": 7,
            }
        ),
        encoding="utf-8",
    )


def _fake_er(title: str = "PM", overall: int = 80) -> Any:
    return SimpleNamespace(
        vacancy=SimpleNamespace(
            title=title, company="Acme", link_or_contact=None, url="u"
        ),
        score=SimpleNamespace(
            track="T",
            scores=SimpleNamespace(overall=overall, map_fit=40),
            verdict=SimpleNamespace(type="match", summary="ок"),
        ),
    )


def test_data_dir_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JOB_AGENT_DATA", str(tmp_path / "d"))
    assert mcp_server.data_dir() == (tmp_path / "d").resolve()


def test_load_env_sets_keys_without_clobbering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=sk-x\n# c\nEMPTY\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("KEEP", "real")
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=sk-x\nKEEP=fromfile\n", encoding="utf-8")
    mcp_server._load_env(tmp_path)
    assert __import__("os").environ["OPENROUTER_API_KEY"] == "sk-x"
    assert __import__("os").environ["KEEP"] == "real"  # реальное окружение приоритетнее


def test_match_dict_shape() -> None:
    d = mcp_server.match_dict(_fake_er("Lead", 92))
    assert d["role"] == "Lead" and d["company"] == "Acme"
    assert d["resume"] == 92 and d["map"] == 40
    assert d["verdict"] == "match" and d["link"] == "u"
    assert d["band"]  # из presentation


def test_load_matches_reads_json(tmp_path: Path) -> None:
    (tmp_path / "results.json").write_text('[{"role": "PM"}]', encoding="utf-8")
    assert mcp_server.load_matches(tmp_path) == [{"role": "PM"}]


def test_load_matches_empty_when_missing_or_bad(tmp_path: Path) -> None:
    assert mcp_server.load_matches(tmp_path) == []
    (tmp_path / "results.json").write_text("{not json", encoding="utf-8")
    assert mcp_server.load_matches(tmp_path) == []


def test_run_search_runs_pipeline_and_writes_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_config(tmp_path)
    captured: dict[str, Any] = {}

    def fake_run_pipeline(config, **kw):  # noqa: ANN001
        captured["since"] = kw["since"]
        captured["window_days"] = (
            __import__("datetime").datetime.now(__import__("datetime").UTC) - kw["since"]
        ).days
        kw["on_result"](_fake_er("PM", 88))
        kw["on_result"](_fake_er("DS", 70))
        return SimpleNamespace(collected=2, after_filter=2, written=2, output_path=None)

    monkeypatch.setattr("job_agent.pipeline.run_pipeline", fake_run_pipeline)
    out = mcp_server.run_search(tmp_path, days=3)
    assert out["count"] == 2
    assert [m["role"] for m in out["matches"]] == ["PM", "DS"]
    assert captured["window_days"] in (2, 3)  # days=3 переопределил конфиг
    # results.json записан — list_matches его увидит
    assert mcp_server.load_matches(tmp_path) == out["matches"]


def test_contacts_for_direct_role_company(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_config(tmp_path)

    def fake_find_contacts(vac, engine, searcher, **kw):  # noqa: ANN001
        return SimpleNamespace(model_dump=lambda: {"candidates": [{"name": "HR"}]})

    monkeypatch.setattr("job_agent.enrich.contacts.find_contacts", fake_find_contacts)
    out = mcp_server.contacts_for(
        tmp_path, role="PM", company="Acme",
        engine=object(), searcher=object(),
    )
    assert out["role"] == "PM" and out["company"] == "Acme"
    assert out["contacts"] == {"candidates": [{"name": "HR"}]}


def test_contacts_for_needs_some_input(tmp_path: Path) -> None:
    _write_config(tmp_path)
    out = mcp_server.contacts_for(tmp_path, engine=object(), searcher=object())
    assert "error" in out
