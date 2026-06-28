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
        run=lambda p: {"collected": 5, "after_filter": 3, "written": 2, "output": "backfill.xlsx"}
    )
    assert runner.start(tmp_path / "config.json") is True
    _wait(runner)
    st = runner.state()
    assert st["status"] == "done"
    assert st["collected"] == 5 and st["after_filter"] == 3 and st["written"] == 2
    assert st["output"] == "backfill.xlsx"


def test_runner_error_surfaces_message(tmp_path: Path) -> None:
    def boom(p: Path) -> dict:
        raise RuntimeError("резюме не найдено")

    runner = BackfillRunner(run=boom)
    runner.start(tmp_path / "config.json")
    _wait(runner)
    st = runner.state()
    assert st["status"] == "error"
    assert "резюме не найдено" in st["message"]


def test_runner_single_run_at_a_time(tmp_path: Path) -> None:
    gate = threading.Event()

    def blocking(p: Path) -> dict:
        gate.wait(2.0)
        return {"collected": 1}

    runner = BackfillRunner(run=blocking)
    assert runner.start(tmp_path / "c.json") is True
    assert runner.is_running() is True
    assert runner.start(tmp_path / "c.json") is False  # второй не запускаем
    gate.set()
    _wait(runner)
    assert runner.state()["status"] == "done"
