"""Калибровка порога пре-фильтра `min_sim` (закрывает открытый калибровочный момент).

Порог близости `min_sim` (косинус резюме↔вакансия) числом не зафиксирован — его
надо подобрать на реальных данных участника. Этот хелпер прогоняет стадии сбора →
нормализации → дедупа → роутинга БЕЗ отсечения (`min_sim=-1`), собирает `best_sim`
каждой прошедшей роль-гейт вакансии, строит распределение и предлагает порог,
разделяющий «релевантную» кучу от «шумовой».

Рекомендация — метод Оцу (Otsu) над гистограммой: ищем границу, максимизирующую
межклассовую дисперсию (естественную «долину» бимодального распределения). Метод
детерминированный и чисто арифметический — тестируется без сети и без модели.

`collect_best_sims` переиспользует строительные блоки `pipeline.py` (коллекторы,
нормализацию, дедуп, роутинг), скоринг (стадия 5, дорогая) не запускает.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Config
from .dedup import SeenStore
from .embeddings import Embedder
from .engines import make_engine
from .engines.base import Engine
from .normalize import normalize_posts
from .pipeline import build_collectors, load_track_resumes, map_examples
from .prefilter import DEFAULT_MIN_SIM, prefilter_and_route

__all__ = [
    "HistBin",
    "SimSummary",
    "CalibrationReport",
    "summarize_sims",
    "recommend_threshold",
    "collect_best_sims",
    "calibrate",
    "report_from_sims",
    "format_report",
]


@dataclass(frozen=True)
class HistBin:
    """Одна корзина гистограммы: полуинтервал [lo, hi) и число попавших значений."""

    lo: float
    hi: float
    count: int


@dataclass(frozen=True)
class SimSummary:
    """Сводка распределения `best_sim`: счётчики, статистики и гистограмма."""

    count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    bins: list[HistBin]


@dataclass(frozen=True)
class CalibrationReport:
    """Итог калибровки: распределение, рекомендованный порог и сплит по нему."""

    summary: SimSummary
    recommended: float
    finalists: int  # best_sim >= recommended
    cut: int  # best_sim < recommended


def summarize_sims(sims: Sequence[float], *, bins: int = 10) -> SimSummary:
    """Посчитать статистики и гистограмму по значениям `best_sim`.

    Гистограмма строится по диапазону [min, max] на `bins` равных корзин;
    последняя корзина включает максимум (полуинтервал справа закрыт у края).
    Пустой вход — ошибка (калибровать нечего).
    """
    if not sims:
        raise ValueError("нет данных для калибровки (best_sim пуст)")
    if bins < 1:
        raise ValueError("bins должен быть >= 1")

    vals = sorted(float(s) for s in sims)
    n = len(vals)
    lo, hi = vals[0], vals[-1]
    mean = sum(vals) / n
    mid = n // 2
    median = vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2

    hist: list[HistBin] = []
    if hi <= lo:
        # Все значения совпали — одна вырожденная корзина.
        hist.append(HistBin(lo=lo, hi=hi, count=n))
    else:
        width = (hi - lo) / bins
        counts = [0] * bins
        for v in vals:
            idx = int((v - lo) / width)
            if idx >= bins:  # значение на правом краю
                idx = bins - 1
            counts[idx] += 1
        for i in range(bins):
            hist.append(HistBin(lo=lo + i * width, hi=lo + (i + 1) * width, count=counts[i]))

    return SimSummary(
        count=n,
        minimum=lo,
        maximum=hi,
        mean=mean,
        median=median,
        bins=hist,
    )


def recommend_threshold(sims: Sequence[float], *, bins: int = 20) -> float:
    """Предложить порог `min_sim` методом Оцу над гистограммой `best_sim`.

    Ищем границу корзины, максимизирующую межклассовую дисперсию (между «шумом»
    слева и «релевантной кучей» справа) — естественную долину бимодального
    распределения. Вырожденные случаи (один уникум / всё совпало) → это значение.
    """
    if not sims:
        raise ValueError("нет данных для калибровки (best_sim пуст)")
    if bins < 1:
        raise ValueError("bins должен быть >= 1")

    vals = [float(s) for s in sims]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return round(lo, 4)

    width = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        idx = int((v - lo) / width)
        if idx >= bins:
            idx = bins - 1
        counts[idx] += 1

    total = len(vals)
    centers = [lo + (i + 0.5) * width for i in range(bins)]
    sum_all = sum(c * n for c, n in zip(centers, counts, strict=True))

    weight_bg = 0.0
    sum_bg = 0.0
    best_var = -1.0
    best_thresh = lo
    # Граница после корзины i отделяет фон (0..i) от переднего плана (i+1..).
    for i in range(bins):
        weight_bg += counts[i]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += centers[i] * counts[i]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_all - sum_bg) / weight_fg
        var_between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if var_between > best_var:
            best_var = var_between
            best_thresh = lo + (i + 1) * width

    return round(best_thresh, 4)


def collect_best_sims(
    config: Config,
    *,
    since: datetime,
    base_dir: str | Path | None = None,
    engine: Engine | None = None,
    embedder: Embedder | None = None,
    collectors=None,
    seen_store: SeenStore | None = None,
) -> list[float]:
    """Собрать `best_sim` всех прошедших роль-гейт вакансий за период (без отсечения).

    Прогоняет стадии 1–4 (`prefilter` с `min_sim=-1`, без лимита финалистов), чтобы
    получить полную картину близостей — и отсечённых, и потенциальных финалистов.
    Стадию скоринга (5) не трогает. Внешние границы инъектируются (тест офлайн);
    seen-store по умолчанию in-memory, чтобы не пачкать боевое хранилище виденных.
    """
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    engine = engine or make_engine(config)
    embedder = embedder or Embedder()
    if collectors is None:
        collectors = build_collectors(config)

    own_store = seen_store is None
    store = seen_store or SeenStore(":memory:")
    try:
        posts = []
        for collector in collectors:
            posts.extend(collector.fetch(since))
        vacancies = normalize_posts(posts, engine, output_lang=config.output_lang)
        fresh = store.filter_new(vacancies)
        track_resumes = load_track_resumes(config, base)
        examples = map_examples(config, base)
        routed = prefilter_and_route(
            fresh,
            config.tracks,
            embedder=embedder,
            track_resumes=track_resumes,
            search_map_examples=examples,
            global_role_gate=config.global_role_gate,
            multi_track=config.multi_track_scoring,
            multi_track_delta=config.multi_track_delta,
            min_sim=-1.0,  # без отсечения: нужна вся картина близостей
            limit=max(1, len(fresh)),
        )
        return [r.best_sim for r in routed]
    finally:
        if own_store:
            store.close()


def calibrate(
    config: Config,
    *,
    days: int | None = None,
    bins: int = 10,
    **kwargs,
) -> CalibrationReport:
    """Прогнать backfill за `days` дней и собрать отчёт-рекомендацию порога.

    `days` по умолчанию — `config.backfill_days`. Возвращает `CalibrationReport`
    с гистограммой, рекомендованным порогом и сплитом вакансий по нему.
    """
    days = days if days is not None else config.backfill_days
    since = datetime.now(UTC) - timedelta(days=days)
    sims = collect_best_sims(config, since=since, **kwargs)
    return report_from_sims(sims, bins=bins)


def report_from_sims(sims: Sequence[float], *, bins: int = 10) -> CalibrationReport:
    """Построить `CalibrationReport` из готового списка `best_sim` (чистая функция)."""
    summary = summarize_sims(sims, bins=bins)
    recommended = recommend_threshold(sims)
    finalists = sum(1 for s in sims if s >= recommended)
    return CalibrationReport(
        summary=summary,
        recommended=recommended,
        finalists=finalists,
        cut=len(sims) - finalists,
    )


def format_report(report: CalibrationReport, *, width: int = 40) -> str:
    """Текстовый отчёт калибровки: статистики, ASCII-гистограмма, рекомендация."""
    s = report.summary
    lines: list[str] = []
    lines.append(
        f"Вакансий (после роль-гейта): {s.count} · "
        f"min {s.minimum:.3f} · median {s.median:.3f} · "
        f"mean {s.mean:.3f} · max {s.maximum:.3f}"
    )
    lines.append("Распределение best_sim:")
    peak = max((b.count for b in s.bins), default=0) or 1
    for b in s.bins:
        bar = "#" * round(b.count / peak * width)
        lines.append(f"  [{b.lo:.3f}, {b.hi:.3f})  {b.count:>4}  {bar}")
    lines.append(
        f"Рекомендованный min_sim: {report.recommended:.3f} "
        f"(финалистов {report.finalists}, отсечётся {report.cut})"
    )
    lines.append(
        f"Текущий мягкий дефолт: {DEFAULT_MIN_SIM}. "
        "Запишите выбранный порог в config.json как \"min_sim\"."
    )
    return "\n".join(lines)
