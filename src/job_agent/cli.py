"""CLI агента подбора вакансий.

Команда `backfill` прогоняет исторический проход (стадии 1–5 + xlsx) за N дней
и пишет `.xlsx`. Команда `nightly` — инкрементальный прогон (только новое с
прошлого раза); в проде её дёргает cron в контейнере раз в сутки, опц. `--serve`
запускает встроенный цикл вне Docker. Команда `calibrate` подбирает порог
пре-фильтра `min_sim` по распределению близостей на backfill (без скоринга).
Логи стадий идут через `logging` в stdout: «собрано N · после фильтра M · топ-K».
Боевые внешние границы строятся по конфигу внутри пайплайна.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from .calibrate import calibrate, format_report
from .config import load_config
from .pipeline import run_backfill, run_nightly
from .prefilter import DEFAULT_LIMIT
from .scheduler import ALWAYS_ON_WARNING, parse_at, serve

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job-agent", description="Локальный агент подбора вакансий"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    backfill = sub.add_parser(
        "backfill", help="Исторический прогон за N дней → .xlsx"
    )
    backfill.add_argument("--config", required=True, help="Путь к config.json")
    backfill.add_argument(
        "--days",
        type=int,
        default=None,
        help="Глубина в днях (дефолт — backfill_days из конфига)",
    )
    backfill.add_argument(
        "--out",
        default="job-agent-result.xlsx",
        help="Путь к выходному .xlsx",
    )
    backfill.add_argument(
        "--min-sim",
        type=float,
        default=None,
        help="Порог близости пре-фильтра (дефолт — min_sim из конфига; калибруется)",
    )
    backfill.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Сколько финалистов скорить (дефолт {DEFAULT_LIMIT})",
    )

    nightly = sub.add_parser(
        "nightly",
        help="Инкрементальный прогон (только новое с прошлого раза) → .xlsx",
    )
    nightly.add_argument("--config", required=True, help="Путь к config.json")
    nightly.add_argument(
        "--out",
        default="job-agent-result.xlsx",
        help="Путь к выходному .xlsx",
    )
    nightly.add_argument(
        "--min-sim",
        type=float,
        default=None,
        help="Порог близости пре-фильтра (дефолт — min_sim из конфига; калибруется)",
    )
    nightly.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Сколько финалистов скорить (дефолт {DEFAULT_LIMIT})",
    )
    nightly.add_argument(
        "--serve",
        action="store_true",
        help="Встроенный цикл вне Docker (по умолчанию один прогон — расписание держит cron)",
    )
    nightly.add_argument(
        "--at",
        default="03:00",
        help="Час ежедневного прогона HH:MM для --serve (дефолт 03:00)",
    )

    calibrate_cmd = sub.add_parser(
        "calibrate",
        help="Подобрать порог пре-фильтра min_sim на backfill (без скоринга)",
    )
    calibrate_cmd.add_argument("--config", required=True, help="Путь к config.json")
    calibrate_cmd.add_argument(
        "--days",
        type=int,
        default=None,
        help="Глубина в днях (дефолт — backfill_days из конфига)",
    )
    calibrate_cmd.add_argument(
        "--bins",
        type=int,
        default=10,
        help="Число корзин гистограммы распределения (дефолт 10)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    if args.command == "backfill":
        config = load_config(args.config)
        base_dir = Path(args.config).resolve().parent
        min_sim = args.min_sim if args.min_sim is not None else config.min_sim
        result = run_backfill(
            config,
            days=args.days,
            output_path=args.out,
            base_dir=base_dir,
            min_sim=min_sim,
            limit=args.limit,
        )
        logging.getLogger("job_agent.cli").info("Готово: %s", result.output_path)
        return 0

    if args.command == "calibrate":
        config = load_config(args.config)
        base_dir = Path(args.config).resolve().parent
        report = calibrate(config, days=args.days, bins=args.bins, base_dir=base_dir)
        logging.getLogger("job_agent.cli").info("%s", format_report(report))
        return 0

    if args.command == "nightly":
        log = logging.getLogger("job_agent.cli")
        log.warning("%s", ALWAYS_ON_WARNING)
        config = load_config(args.config)
        base_dir = Path(args.config).resolve().parent
        min_sim = args.min_sim if args.min_sim is not None else config.min_sim

        def _run() -> None:
            result = run_nightly(
                config,
                output_path=args.out,
                base_dir=base_dir,
                min_sim=min_sim,
                limit=args.limit,
            )
            log.info("Готово: %s", result.output_path)

        if args.serve:
            at = parse_at(args.at)
            log.info("Встроенный цикл: ежедневно в %s", args.at)
            serve(_run, at=at)
        else:
            _run()
        return 0

    parser.error(f"неизвестная команда: {args.command}")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
