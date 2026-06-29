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
        run=lambda p, prog, res, item, agent: {
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
    def boom(p: Path, prog, res, item, agent) -> dict:
        raise RuntimeError("резюме не найдено")

    runner = BackfillRunner(run=boom)
    runner.start(tmp_path / "config.json")
    _wait(runner)
    st = runner.state()
    assert st["status"] == "error"
    assert "резюме не найдено" in st["message"]


def test_runner_progress_updates_state(tmp_path: Path) -> None:
    gate = threading.Event()

    def run(p: Path, prog, res, item, agent) -> dict:
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

    def run(p: Path, prog, res, item, agent) -> dict:
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

    def blocking(p: Path, prog, res, item, agent) -> dict:
        gate.wait(2.0)
        return {"collected": 1}

    runner = BackfillRunner(run=blocking)
    assert runner.start(tmp_path / "c.json") is True
    assert runner.is_running() is True
    assert runner.start(tmp_path / "c.json") is False  # второй не запускаем
    gate.set()
    _wait(runner)
    assert runner.state()["status"] == "done"


def test_runner_seeds_results_from_results_json(tmp_path: Path) -> None:
    """Подборка прошлого прогона подхватывается из results.json при старте."""
    (tmp_path / "results.json").write_text(
        '[{"role": "PM", "company": "Acme"}]', encoding="utf-8"
    )
    runner = BackfillRunner(results_dir=tmp_path)
    assert runner.results() == [{"role": "PM", "company": "Acme"}]


def test_runner_empty_results_without_dir_or_file(tmp_path: Path) -> None:
    assert BackfillRunner().results() == []
    assert BackfillRunner(results_dir=tmp_path).results() == []  # файла нет
