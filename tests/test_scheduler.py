"""Тесты планировщика: расчёт следующего запуска без реального сна."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import time as dtime

import pytest

from job_agent.scheduler import (
    ALWAYS_ON_WARNING,
    DEFAULT_NIGHTLY_AT,
    next_run,
    parse_at,
    serve,
)


def test_parse_at_valid() -> None:
    assert parse_at("03:00") == dtime(3, 0)
    assert parse_at(" 23:59 ") == dtime(23, 59)


@pytest.mark.parametrize("value", ["3", "03-00", "aa:bb", "24:00", "12:60", ""])
def test_parse_at_rejects_garbage(value: str) -> None:
    with pytest.raises(ValueError):
        parse_at(value)


def test_next_run_later_today() -> None:
    after = datetime(2026, 6, 28, 1, 30, tzinfo=UTC)
    assert next_run(dtime(3, 0), after=after) == datetime(2026, 6, 28, 3, 0, tzinfo=UTC)


def test_next_run_rolls_to_tomorrow_when_passed() -> None:
    after = datetime(2026, 6, 28, 5, 0, tzinfo=UTC)
    assert next_run(dtime(3, 0), after=after) == datetime(2026, 6, 29, 3, 0, tzinfo=UTC)


def test_next_run_strictly_after_when_equal() -> None:
    # Ровно в назначенный момент → следующий день, не зацикливаемся на now.
    after = datetime(2026, 6, 28, 3, 0, tzinfo=UTC)
    assert next_run(dtime(3, 0), after=after) == datetime(2026, 6, 29, 3, 0, tzinfo=UTC)


def test_next_run_preserves_tzinfo() -> None:
    after = datetime(2026, 6, 28, 1, 0, tzinfo=UTC)
    assert next_run(DEFAULT_NIGHTLY_AT, after=after).tzinfo is UTC


def test_serve_loop_runs_without_real_sleep() -> None:
    # Часы шагают на час за итерацию, сон фейковый — реального ожидания нет.
    clock_state = {"now": datetime(2026, 6, 28, 0, 0, tzinfo=UTC)}
    slept: list[float] = []
    runs: list[int] = []

    def clock() -> datetime:
        return clock_state["now"]

    def sleeper(delay: float) -> None:
        slept.append(delay)
        clock_state["now"] = clock_state["now"] + timedelta(seconds=delay)

    def run() -> None:
        runs.append(1)

    # Остановиться после двух прогонов.
    def stop() -> bool:
        return len(runs) >= 2

    total = serve(run, at=dtime(3, 0), clock=clock, sleeper=sleeper, stop=stop)

    assert total == 2
    assert len(runs) == 2
    # Первый сон — 3 часа до 03:00, второй — сутки до следующего 03:00.
    assert slept == [3 * 3600.0, 24 * 3600.0]


def test_always_on_warning_mentions_host() -> None:
    assert "хост" in ALWAYS_ON_WARNING.lower()
