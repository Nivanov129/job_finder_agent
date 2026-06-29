"""Юнит-тесты фонового backfill-раннера — фейк-прогон, без пайплайна/сети."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from webui.runner import BackfillRunner


def _wait(runner: BackfillRunner, timeout: float = 2.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end and runner.is_running():
        time.sleep(0.01)


def test_runner_done_with_counters(tmp_path: Path) -> None:
    runner = BackfillRunner(
        run=lambda p, prog, res, item, agent, notify=False: {
            "collected": 5, "after_filter": 3, "written": 2, "output": "backfill.xlsx"
        }
    )
    assert runner.start(tmp_path / "config.json") is True
    _wait(runner)
    st = runner.state()
    assert st["status"] == "done"
    assert st["collected"] == 5 and st["after_filter"] == 3 and st["written"] == 2
    assert st["output"] == "backfill.xlsx"


def test_runner_error_surfaces_message(tmp_path: Path) -> None:
    def boom(p: Path, prog, res, item, agent, notify=False) -> dict:
        raise RuntimeError("резюме не найдено")

    runner = BackfillRunner(run=boom)
    runner.start(tmp_path / "config.json")
    _wait(runner)
    st = runner.state()
    assert st["status"] == "error"
    assert "резюме не найдено" in st["message"]


def test_runner_progress_updates_state(tmp_path: Path) -> None:
    gate = threading.Event()

    def run(p: Path, prog, res, item, agent, notify=False) -> dict:
        prog("normalize", {"collected": 7})
        item({"phase": "read", "role": "Product Manager", "company": "Avito"})
        gate.wait(2.0)
        return {"written": 1}

    runner = BackfillRunner(run=run)
    runner.start(tmp_path / "c.json")
    for _ in range(200):  # ждём, пока прогресс долетит до состояния
        if runner.state()["collected"] == 7:
            break
        time.sleep(0.01)
    st = runner.state()
    assert st["collected"] == 7 and st["stage"] == "normalize"
    assert st["feed"] and st["feed"][0]["role"] == "Product Manager"
    gate.set()
    _wait(runner)


def test_last_run_roundtrip(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from webui.runner import read_last_run, write_last_run

    p = tmp_path / "last_run.json"
    assert read_last_run(p) is None
    when = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    write_last_run(p, when)
    assert read_last_run(p) == when


def test_agent_triggers_run_in_agent_mode(tmp_path: Path) -> None:
    calls: list[bool] = []

    def run(p: Path, prog, res, item, agent, notify=False) -> dict:
        calls.append(agent)
        return {}

    runner = BackfillRunner(run=run)
    runner.start_agent(tmp_path / "c.json", interval_min=60)
    for _ in range(300):  # первый прогон стартует сразу, не ждём интервал
        if calls:
            break
        time.sleep(0.01)
    runner.stop_agent()
    assert calls == [True]  # один авто-прогон, agent_mode=True
    assert runner.agent_status()["interval_min"] == 60


def test_runner_single_run_at_a_time(tmp_path: Path) -> None:
    gate = threading.Event()

    def blocking(p: Path, prog, res, item, agent, notify=False) -> dict:
        gate.wait(2.0)
        return {"collected": 1}

    runner = BackfillRunner(run=blocking)
    assert runner.start(tmp_path / "c.json") is True
    assert runner.is_running() is True
    assert runner.start(tmp_path / "c.json") is False  # второй не запускаем
    gate.set()
    _wait(runner)
    assert runner.state()["status"] == "done"


def test_runner_results_from_matchstore(tmp_path: Path) -> None:
    """Подборка читается из накопительной БД (matches.db), переживая рестарт."""
    from job_agent.matchstore import MatchStore

    with MatchStore(tmp_path / "matches.db") as store:
        store.upsert({"role": "PM", "company": "Acme", "resume": 80, "map": 40})
    runner = BackfillRunner(results_dir=tmp_path)
    rows = runner.results()
    assert [r["role"] for r in rows] == ["PM"]


def test_runner_archive_via_store(tmp_path: Path) -> None:
    from job_agent.matchstore import MatchStore

    with MatchStore(tmp_path / "matches.db") as store:
        key = store.upsert({"role": "PM", "company": "Acme"})
    runner = BackfillRunner(results_dir=tmp_path)
    assert runner.archive(key) is True
    assert runner.results() == []  # ушла из активных


def test_runner_empty_results_without_dir_or_db(tmp_path: Path) -> None:
    assert BackfillRunner().results() == []
    assert BackfillRunner(results_dir=tmp_path).results() == []  # БД нет


def test_runner_threads_notify_flag(tmp_path: Path) -> None:
    """start(notify=True) пробрасывает флаг в прогон (ручной «слать в ТГ»)."""
    seen: dict[str, bool] = {}

    def run(p: Path, prog, res, item, agent, notify=False) -> dict:
        seen["notify"] = notify
        return {}

    runner = BackfillRunner(run=run)
    runner.start(tmp_path / "c.json", notify=True)
    for _ in range(200):
        if "notify" in seen:
            break
        time.sleep(0.01)
    _wait(runner)
    assert seen.get("notify") is True
