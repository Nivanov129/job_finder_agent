"""Фоновый запуск backfill из web-UI: один прогон за раз + статус для опроса.

Реальный пайплайн (`run_backfill`) спрятан за инъекцией `run` — юнит-тесты не
ходят в сеть/движок. Прогон идёт в фоновом потоке (UI остаётся отзывчивым),
страница «Прогон» опрашивает статус и показывает счётчики/ошибку/ссылку на .xlsx.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

__all__ = ["BackfillRunner", "RunState", "BackfillFn"]


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


# (config_path, on_progress) -> счётчики прогона; бросает исключение при ошибке.
ProgressFn = Callable[[str, dict[str, int]], None]
BackfillFn = Callable[[Path, ProgressFn], dict[str, Any]]


class BackfillRunner:
    """Один backfill-прогон за раз в фоновом потоке; потокобезопасный статус."""

    def __init__(self, *, run: BackfillFn | None = None) -> None:
        self._run = run or _default_run
        self._state = RunState()
        self._lock = threading.Lock()

    def state(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._state)

    def is_running(self) -> bool:
        with self._lock:
            return self._state.status == "running"

    def start(self, config_path: Path | str) -> bool:
        """Запустить прогон. False — если уже идёт (не запускаем второй)."""
        with self._lock:
            if self._state.status == "running":
                return False
            self._state = RunState(status="running", message="прогон запущен…")
        threading.Thread(
            target=self._worker, args=(Path(config_path),), daemon=True
        ).start()
        return True

    def _on_progress(self, stage: str, counts: dict[str, int]) -> None:
        with self._lock:
            if self._state.status != "running":
                return
            self._state.stage = stage
            for key in ("collected", "to_normalize", "normalized", "after_filter", "scored"):
                if key in counts:
                    setattr(self._state, key, counts[key])

    def _worker(self, config_path: Path) -> None:
        try:
            res = self._run(config_path, self._on_progress)
            new = RunState(status="done", message="готово")
            new.collected = int(res.get("collected", 0))
            new.after_filter = int(res.get("after_filter", 0))
            new.written = int(res.get("written", 0))
            new.output = str(res.get("output", ""))
        except Exception as exc:  # ошибка прогона — показываем причину в UI
            new = RunState(status="error", message=str(exc)[:500])
        with self._lock:
            self._state = new


def _default_run(  # pragma: no cover - пайплайн
    config_path: Path, on_progress: ProgressFn
) -> dict[str, Any]:
    """Боевой прогон: грузит конфиг и гоняет backfill, пишет .xlsx рядом.

    Перед запуском подмешиваем свежий `.env` в окружение — токен движка, ключ
    Ollama и сессия Telegram могли быть сохранены уже после старта контейнера
    (UI-прогон идёт в этом же процессе, чьё окружение иначе устарело).
    """
    import os

    from job_agent.config import load_config
    from job_agent.pipeline import run_backfill

    from .env_store import parse_env

    base = Path(config_path).resolve().parent
    os.environ.update(parse_env(base / ".env"))
    config = load_config(config_path)
    out = base / "backfill.xlsx"
    result = run_backfill(
        config, base_dir=base, output_path=out, on_progress=on_progress
    )
    return {
        "collected": result.collected,
        "after_filter": result.after_filter,
        "written": result.written,
        "output": out.name if result.output_path else "",
    }
