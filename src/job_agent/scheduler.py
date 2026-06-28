"""Планировщик ночного прогона.

В проде расписание держит cron внутри контейнера: он дёргает `job-agent nightly`
раз в сутки в назначенный час. Этот модуль — чистая логика расчёта следующего
запуска (для опц. встроенного цикла `--serve` вне Docker и для тестов без
реального сна) плюс предупреждение про always-on.

`next_run` детерминирован и не спит: даёт ближайший момент `at` строго после
заданной точки. `serve` — тонкий цикл поверх него; часы и сон инъектируются,
поэтому тестируется без `time.sleep`.

Always-on: ночной мониторинг работает только при включённом хосте. Если машина
спит/выключена в назначенный час — прогон этого дня пропускается (backfill
закроет пробел по требованию).
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import time as dtime

__all__ = [
    "ALWAYS_ON_WARNING",
    "DEFAULT_NIGHTLY_AT",
    "next_run",
    "parse_at",
    "serve",
]

ALWAYS_ON_WARNING = (
    "always-on: ночной мониторинг требует включённого хоста. Если машина спит или "
    "выключена в назначенный час — прогон этого дня пропускается; пробел закрывается "
    "backfill по требованию."
)

DEFAULT_NIGHTLY_AT = dtime(hour=3, minute=0)


def parse_at(value: str) -> dtime:
    """Разобрать строку 'HH:MM' в `time`. Внятная ошибка на мусоре."""
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"время должно быть в формате HH:MM, получено: {value!r}")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"время должно быть в формате HH:MM, получено: {value!r}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"час 0–23 и минута 0–59, получено: {value!r}")
    return dtime(hour=hour, minute=minute)


def next_run(at: dtime, *, after: datetime) -> datetime:
    """Ближайший момент `at` (час:минута) строго после `after`.

    Если сегодняшний `at` уже наступил (или равен `after`) — берём завтрашний.
    Tzinfo `after` сохраняется (для tz-aware часов).
    """
    candidate = after.replace(
        hour=at.hour, minute=at.minute, second=0, microsecond=0
    )
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate


def serve(
    run: Callable[[], object],
    *,
    at: dtime = DEFAULT_NIGHTLY_AT,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleeper: Callable[[float], None] = _time.sleep,
    stop: Callable[[], bool] | None = None,
) -> int:
    """Встроенный цикл: спать до ближайшего `at`, затем дёрнуть `run`, повторять.

    Альтернатива cron для запуска вне Docker. Часы (`clock`) и сон (`sleeper`)
    инъектируются — в тестах цикл крутится без реального ожидания. `stop` (если
    задан) проверяется перед каждым ожиданием; вернул True → выходим. Возвращает
    число выполненных прогонов.
    """
    runs = 0
    while True:
        if stop is not None and stop():
            return runs
        now = clock()
        target = next_run(at, after=now)
        delay = (target - now).total_seconds()
        if delay > 0:
            sleeper(delay)
        run()
        runs += 1
