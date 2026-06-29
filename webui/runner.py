"""Фоновый запуск прогонов из web-UI: разовый backfill и режим агента.

Реальный пайплайн спрятан за инъекцией `run` — юнит-тесты не ходят в сеть/движок.
Прогон идёт в фоновом потоке (UI отзывчив), страница «Прогон» опрашивает статус.

Режим агента: фоновый цикл сам запускает прогон каждые N минут и догоняет
пропущенное — собирает вакансии с момента ПОСЛЕДНЕГО прогона (время хранится в
`last_run.json`). Без последнего времени — окно `backfill_days`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["BackfillRunner", "RunState", "BackfillFn", "read_last_run", "write_last_run"]


# ── Время последнего прогона (для догоняющего сбора) ──────────────────────────


def read_last_run(path: Path | str) -> datetime | None:
    """Прочитать ISO-время последнего прогона из файла (или None)."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8")).get("last_run", "")
        return datetime.fromisoformat(raw) if raw else None
    except (OSError, ValueError):
        return None


def write_last_run(path: Path | str, when: datetime) -> None:
    """Атомарно записать ISO-время последнего прогона."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps({"last_run": when.isoformat()}), encoding="utf-8")
    tmp.replace(p)


@dataclass
class RunState:
    """Состояние прогона для опроса из UI (без внутренностей пайплайна)."""

    status: str = "idle"  # idle | running | done | error
    message: str = ""
    stage: str = ""  # collect | normalize | score (живой этап)
    collected: int = 0
    to_normalize: int = 0  # сколько постов идёт в нормализацию (после фильтра)
    normalized: int = 0  # сколько уже нормализовано
    after_filter: int = 0
    scored: int = 0  # сколько финалистов уже оценено
    written: int = 0
    output: str = ""  # имя файла .xlsx для скачивания (когда готово)


# (config_path, on_progress, on_result, on_item, agent_mode) -> счётчики; бросает при ошибке.
ProgressFn = Callable[[str, dict[str, int]], None]
ResultFn = Callable[[dict[str, Any]], None]
ItemFn = Callable[[dict[str, Any]], None]
BackfillFn = Callable[[Path, ProgressFn, ResultFn, ItemFn, bool], dict[str, Any]]

_FEED_MAX = 24  # сколько последних «прочитанных/оцениваемых» постов держим в ленте


# Компактный вид обогащённого результата — общий шейпер в ядре (та же форма для
# UI, БД подборки и MCP). Оставляем имя result_to_dict для совместимости.
from job_agent.output.summary import match_dict as result_to_dict  # noqa: E402


class BackfillRunner:
    """Прогоны (разовый + агент) в фоне; потокобезопасный статус."""

    def __init__(
        self, *, run: BackfillFn | None = None, results_dir: Path | str | None = None
    ) -> None:
        self._run = run or _default_run
        # Каталог данных → локальная БД подборки (matches.db). Подборку читаем из
        # неё (накопление между прогонами), а не из памяти — иначе на свежем
        # процессе (рестарт стека) UI был бы пуст. None (тесты с инъекцией run) →
        # отдаём in-memory результаты прогона.
        self._matches_db = (
            Path(results_dir) / "matches.db" if results_dir is not None else None
        )
        self._state = RunState()
        self._results: list[dict[str, Any]] = []
        self._feed: list[dict[str, Any]] = []  # живая лента: что AI читает/оценивает
        self._lock = threading.Lock()
        # агент
        self._agent_stop = threading.Event()
        self._agent_thread: threading.Thread | None = None
        self._agent_interval = 30  # минуты
        self._agent_config: Path | None = None
        self._next_run = 0.0  # time.monotonic() следующего запуска

    # — разовый прогон —

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {**asdict(self._state), "feed": list(self._feed)}

    def is_running(self) -> bool:
        with self._lock:
            return self._state.status == "running"

    def start(self, config_path: Path | str, *, agent_mode: bool = False) -> bool:
        """Запустить прогон. False — если уже идёт (не запускаем второй)."""
        with self._lock:
            if self._state.status == "running":
                return False
            self._state = RunState(status="running", message="прогон запущен…")
            self._results = []  # новый прогон — сбрасываем результаты
            self._feed = []  # и живую ленту
        threading.Thread(
            target=self._worker, args=(Path(config_path), agent_mode), daemon=True
        ).start()
        return True

    def results(self) -> list[dict[str, Any]]:
        """Подборка: из БД (накопленная, активная) либо in-memory (тесты)."""
        if self._matches_db is not None:
            from job_agent.matchstore import MatchStore

            with MatchStore(self._matches_db) as store:
                return store.list()
        with self._lock:
            return list(self._results)

    def archive(self, key: str) -> bool:
        """Убрать вакансию из подборки (статус archived). True — если нашлась."""
        if self._matches_db is None:
            return False
        from job_agent.matchstore import MatchStore

        with MatchStore(self._matches_db) as store:
            return store.set_status(key, "archived")

    def _on_result(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._results.append(item)

    def _on_item(self, item: dict[str, Any]) -> None:
        """Живая лента прогона: добавляем самый свежий пост в начало, режем хвост."""
        with self._lock:
            if self._state.status != "running":
                return
            self._feed.insert(0, item)
            del self._feed[_FEED_MAX:]

    def _on_progress(self, stage: str, counts: dict[str, int]) -> None:
        with self._lock:
            if self._state.status != "running":
                return
            self._state.stage = stage
            for key in ("collected", "to_normalize", "normalized", "after_filter", "scored"):
                if key in counts:
                    setattr(self._state, key, counts[key])

    def _worker(self, config_path: Path, agent_mode: bool) -> None:
        try:
            res = self._run(
                config_path, self._on_progress, self._on_result, self._on_item, agent_mode
            )
            new = RunState(status="done", message="готово")
            new.collected = int(res.get("collected", 0))
            new.after_filter = int(res.get("after_filter", 0))
            new.written = int(res.get("written", 0))
            new.output = str(res.get("output", ""))
        except Exception as exc:  # ошибка прогона — показываем причину в UI
            new = RunState(status="error", message=str(exc)[:500])
        with self._lock:
            self._state = new

    # — режим агента —

    def start_agent(self, config_path: Path | str, interval_min: int) -> None:
        """Включить агента: запускать прогон каждые `interval_min` минут."""
        with self._lock:
            self._agent_interval = max(1, int(interval_min))
            self._agent_config = Path(config_path)
            if self._agent_thread is not None and self._agent_thread.is_alive():
                return  # уже включён — обновили интервал
            self._agent_stop.clear()
            self._agent_thread = threading.Thread(target=self._agent_loop, daemon=True)
            self._agent_thread.start()

    def stop_agent(self) -> None:
        self._agent_stop.set()

    def agent_status(self) -> dict[str, Any]:
        with self._lock:
            enabled = self._agent_thread is not None and self._agent_thread.is_alive()
            secs = max(0, int(self._next_run - time.monotonic())) if enabled else 0
            return {
                "enabled": enabled,
                "interval_min": self._agent_interval,
                "seconds_to_next": secs,
            }

    def _agent_loop(self) -> None:
        while not self._agent_stop.is_set():
            if self._agent_config is not None and not self.is_running():
                self.start(self._agent_config, agent_mode=True)
            interval = self._agent_interval * 60
            with self._lock:
                self._next_run = time.monotonic() + interval
            self._agent_stop.wait(interval)


def _default_run(  # pragma: no cover - пайплайн
    config_path: Path,
    on_progress: ProgressFn,
    on_result: ResultFn,
    on_item: ItemFn,
    agent_mode: bool = False,
) -> dict[str, Any]:
    """Боевой прогон: грузит конфиг и гоняет пайплайн, пишет .xlsx рядом.

    Перед запуском подмешиваем свежий `.env` (токены/сессия могли сохраниться уже
    после старта контейнера). В режиме агента собираем с момента последнего
    прогона (`last_run.json`), иначе — окно `backfill_days`. После успеха пишем
    новое время последнего прогона.
    """
    import os
    from datetime import timedelta

    from job_agent.config import load_config
    from job_agent.dedup import SeenStore
    from job_agent.pipeline import run_pipeline

    from .env_store import parse_env

    base = Path(config_path).resolve().parent
    os.environ.update(parse_env(base / ".env"))
    config = load_config(config_path)
    last_run_file = base / "last_run.json"
    # Seen-дедуп нужен АГЕНТУ (не переоценивать/не пушить одно и то же между
    # прогонами). Для разового «Подбора за период» он вреден: пользователь хочет
    # ВСЕ совпадения периода каждый раз — поэтому даём свежий in-memory store
    # (дедуп только внутри прогона, без памяти между прогонами).
    seen_store = None if agent_mode else SeenStore(":memory:")

    now = datetime.now(UTC)
    last = read_last_run(last_run_file)
    if agent_mode and last is not None:
        since = last  # догоняем пропущенное с прошлого прогона
    else:
        since = now - timedelta(days=config.backfill_days)

    out = base / "backfill.xlsx"
    # В агент-режиме копим финалистов (EnrichedResult), чтобы после прогона
    # отправить НОВЫЕ вакансии в Telegram-бот владельца.
    finalists: list[Any] = []
    # Подборку накапливаем в локальной БД (matches.db): апсёрт по мере оценки —
    # подборка растёт и сразу видна в UI/MCP, а не перетирается прогоном.
    from job_agent.matchstore import MatchStore

    store = MatchStore(base / "matches.db")

    def _on_result_er(er: Any) -> None:
        if agent_mode:
            finalists.append(er)
        d = result_to_dict(er)
        try:
            store.upsert(d)
        except Exception as exc:  # БД не должна валить прогон
            logging.getLogger("job_agent.webui.runner").warning(
                "matches.db upsert пропущен: %s", str(exc)[:120]
            )
        on_result(d)

    try:
        result = run_pipeline(
            config, since=since, base_dir=base, output_path=out,
            seen_store=seen_store,
            on_progress=on_progress,
            on_result=_on_result_er,
            on_item=on_item,
        )
    finally:
        store.close()
    write_last_run(last_run_file, now)
    if agent_mode and finalists:
        try:
            from .notify import notify_new_vacancies

            notify_new_vacancies(config, finalists)
        except Exception as exc:  # бот-уведомление не должно валить прогон
            logging.getLogger("job_agent.webui.runner").warning(
                "Бот-уведомление пропущено: %s", str(exc)[:160]
            )
    return {
        "collected": result.collected,
        "after_filter": result.after_filter,
        "written": result.written,
        "output": out.name if result.output_path else "",
    }
