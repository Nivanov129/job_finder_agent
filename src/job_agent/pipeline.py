"""Сборка пайплайна (стадии 1–5 + xlsx) и backfill-прогон.

`pipeline.py` сшивает стадии, а не инлайнит их логику: коллекторы (1) →
нормализация (2) → дедуп (3) → пре-фильтр/роутинг (4) → скоринг (5) → xlsx (7).
Каждая стадия живёт своим модулем с явным интерфейсом; здесь только оркестрация
и подготовка входов (чтение текстов резюме/карты, выбор коллекторов по конфигу).

Внешние границы инъектируются (движок, эмбеддер, коллекторы, seen-store) — это и
делает end-to-end тест полностью офлайновым. Без инъекции строятся боевые
реализации по конфигу. Дефолтный порог пре-фильтра `min_sim` конфигурируем
(аргумент/CLI), пока не зафиксирован калибровкой (Task 4.4).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .collectors.base import Collector
from .collectors.getmatch import GetmatchCollector
from .collectors.telegram_private import make_private_collector
from .collectors.telegram_public import TelegramPublicCollector
from .collectors.vseti import VsetiCollector
from .config import Config
from .dedup import SeenStore
from .embeddings import Embedder
from .engines import make_engine
from .engines.base import Engine
from .enrich.contacts import find_contacts
from .enrich.cover import write_cover_letter
from .models import EnrichedResult
from .normalize import normalize_posts
from .output.xlsx import write_xlsx
from .prefilter import DEFAULT_LIMIT, DEFAULT_MIN_SIM, MapExample, prefilter_and_route
from .scoring import score_routed
from .websearch import make_searcher
from .websearch.base import Searcher

__all__ = [
    "RunResult",
    "build_collectors",
    "load_track_resumes",
    "load_cover_templates",
    "map_examples",
    "run_pipeline",
    "run_backfill",
    "run_nightly",
]

logger = logging.getLogger("job_agent.pipeline")


@dataclass
class RunResult:
    """Итог прогона пайплайна: счётчики стадий + финальные обогащённые результаты."""

    collected: int = 0
    after_filter: int = 0
    written: int = 0
    results: list[EnrichedResult] = field(default_factory=list)
    output_path: Path | None = None


def _extract_pdf_text(path: Path) -> str:
    """Текстовый слой PDF через pypdf (страницы склеиваются через перевод строки)."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def _read_document(path: str | Path, base_dir: Path) -> str:
    """Прочитать резюме/шаблон/карту как текст, резолвя путь от base_dir.

    `.pdf` извлекается через pypdf (текстовый слой), остальное читается как utf-8
    (md/txt/json). Скан-PDF без текстового слоя дадут пустую/неполную строку —
    пользователь загружает текстовый PDF.
    """
    p = Path(path)
    if not p.is_absolute():
        p = base_dir / p
    if p.suffix.lower() == ".pdf":
        return _extract_pdf_text(p)
    return p.read_text(encoding="utf-8")


def load_track_resumes(config: Config, base_dir: Path) -> dict[str, str]:
    """id трека → текст резюме. Пути из `track.resume_path` (относительно base_dir).

    Чтение текста — забота оркестратора (пре-фильтр работает уже с готовыми
    строками). Поддерживаются PDF (текстовый слой) и текстовые форматы (md/txt).
    """
    resumes: dict[str, str] = {}
    for track in config.tracks:
        resumes[track.id] = _read_document(track.resume_path, base_dir)
    return resumes


def load_cover_templates(config: Config, base_dir: Path) -> dict[str, str | None]:
    """id трека → текст шаблона сопроводительного (или `None`, если не задан).

    Шаблон опционален: трек без `cover_template_path` → `None`, и тогда
    сопроводительное для него не готовится (см. гейт в `enrich/cover.py`).
    """
    templates: dict[str, str | None] = {}
    for track in config.tracks:
        if track.cover_template_path:
            templates[track.id] = _read_document(track.cover_template_path, base_dir)
        else:
            templates[track.id] = None
    return templates


def map_examples(config: Config, base_dir: Path) -> list[MapExample]:
    """Примеры карты поиска для пре-фильтра/скоринга: `(текст, track_id|None)`.

    Структурированные примеры из `search_map.examples` + (если задан) содержимое
    файла `search_map.path` как общий эталон (`track_id=None`).
    """
    examples: list[MapExample] = []
    sm = config.search_map
    if sm is None:
        return examples
    for ex in sm.examples:
        examples.append((ex.text, ex.track_id))
    if sm.path:
        path = Path(sm.path)
        resolved = path if path.is_absolute() else base_dir / path
        if resolved.exists():
            text = _read_document(resolved, base_dir).strip()
            if text:
                examples.append((text, None))
    return examples


def build_collectors(
    config: Config,
    *,
    public_fetcher=None,
    private_fetcher=None,
    vseti_fetcher=None,
    getmatch_fetcher=None,
) -> list[Collector]:
    """Собрать коллекторы по конфигу (стадия 1). Фетчеры инъектируются в тестах.

    Публичные TG-каналы — через `t.me/s/`; приватные — Telethon (только при
    creds или инъекции fetcher); агрегаторы — при `use_aggregators`.
    """
    collectors: list[Collector] = []

    public_handles = [c.handle for c in config.tg_channels if not c.private]
    if public_handles:
        collectors.append(TelegramPublicCollector(public_handles, fetcher=public_fetcher))

    private_handles = [c.handle for c in config.tg_channels if c.private]
    if private_handles:
        private = make_private_collector(
            private_handles, config.telethon_creds, fetcher=private_fetcher
        )
        if private is not None:
            collectors.append(private)

    if config.use_aggregators:
        collectors.append(VsetiCollector(fetcher=vseti_fetcher))
        collectors.append(GetmatchCollector(fetcher=getmatch_fetcher))

    return collectors


def run_pipeline(
    config: Config,
    *,
    since: datetime,
    output_path: str | Path | None = None,
    base_dir: str | Path | None = None,
    engine: Engine | None = None,
    embedder: Embedder | None = None,
    collectors: Sequence[Collector] | None = None,
    seen_store: SeenStore | None = None,
    searcher: Searcher | None = None,
    min_sim: float = DEFAULT_MIN_SIM,
    limit: int = DEFAULT_LIMIT,
) -> RunResult:
    """Прогнать стадии 1–5 + xlsx за один проход.

    `since` — нижняя граница даты постов. Внешние границы (движок, эмбеддер,
    коллекторы, seen-store) можно инъектировать; без инъекции строятся боевые по
    конфигу. `output_path` задан → пишем `.xlsx` (колонка направления скрыта при
    единственном треке). Возвращает счётчики и обогащённые результаты.
    """
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    engine = engine or make_engine(config)
    embedder = embedder or Embedder()
    if collectors is None:
        collectors = build_collectors(config)

    own_store = seen_store is None
    store = seen_store or SeenStore()
    try:
        # 1. Сбор.
        posts = []
        for collector in collectors:
            posts.extend(collector.fetch(since))
        collected = len(posts)

        # 2. Нормализация.
        vacancies = normalize_posts(posts, engine, output_lang=config.output_lang)

        # 3. Дедуп (кросс-источник + внутрипрогонный), помечаем виденными.
        fresh = store.filter_new(vacancies)

        # 4. Пре-фильтр + роутинг.
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
            min_sim=min_sim,
            limit=limit,
        )
        after_filter = len(routed)

        # 5. Скоринг финалистов.
        tracks_by_id = {t.id: t for t in config.tracks}
        # `score.track` несёт имя направления ({{track_name}} из промта), не id —
        # резолвим трек по имени с откатом на `best_track` из роутинга.
        tracks_by_name = {t.name: t for t in config.tracks}
        cover_templates = load_cover_templates(config, base)
        # Web-поиск для контактов строим лениво и только при включённой стадии.
        contact_searcher = searcher
        if config.enable_contacts and contact_searcher is None:
            contact_searcher = make_searcher(config)

        results: list[EnrichedResult] = []
        for rv in routed:
            score = score_routed(
                rv,
                tracks_by_id,
                engine,
                track_resumes=track_resumes,
                search_map_examples=examples,
                global_disqualifiers=config.global_disqualifiers,
                multi_track_scoring=config.multi_track_scoring,
                output_lang=config.output_lang,
            )
            if score is None:
                continue

            # 6. Обогащение финалистов: сопроводительное (гейт по порогу + шаблон)
            #    и опц. контакт-ассист (только при enable_contacts).
            track = tracks_by_name.get(score.track) or tracks_by_id.get(rv.best_track)
            track_id = track.id if track is not None else rv.best_track
            cover_letter = write_cover_letter(
                score,
                rv.vacancy,
                engine,
                cover_template=cover_templates.get(track_id),
                track_resume=track_resumes.get(track_id, ""),
                threshold=config.cover_letter_threshold,
                output_lang=config.output_lang,
            )
            contacts = None
            if config.enable_contacts and contact_searcher is not None:
                contacts = find_contacts(
                    rv.vacancy,
                    engine,
                    contact_searcher,
                    track_name=track.name if track is not None else score.track,
                    enable_contacts=True,
                    output_lang=config.output_lang,
                )

            results.append(
                EnrichedResult(
                    vacancy=rv.vacancy,
                    score=score,
                    cover_letter=cover_letter,
                    contacts=contacts,
                )
            )

        # 7. Выход (.xlsx).
        out_path: Path | None = None
        if output_path is not None:
            out_path = write_xlsx(
                results, output_path, is_single_track=config.is_single_track
            )

        written = len(results)
        logger.info("собрано %d · после фильтра %d · топ-%d", collected, after_filter, written)

        return RunResult(
            collected=collected,
            after_filter=after_filter,
            written=written,
            results=results,
            output_path=out_path,
        )
    finally:
        if own_store:
            store.close()


def run_backfill(
    config: Config,
    *,
    days: int | None = None,
    output_path: str | Path | None = None,
    **kwargs,
) -> RunResult:
    """Backfill-прогон: история за `days` дней (дефолт — `config.backfill_days`).

    Тонкая обёртка над `run_pipeline`: считает `since` от текущего момента,
    остальное прокидывает как есть.
    """
    days = days if days is not None else config.backfill_days
    since = datetime.now(UTC) - timedelta(days=days)
    return run_pipeline(config, since=since, output_path=output_path, **kwargs)


def run_nightly(
    config: Config,
    *,
    now: datetime | None = None,
    lookback_days: int | None = None,
    output_path: str | Path | None = None,
    seen_store: SeenStore | None = None,
    **kwargs,
) -> RunResult:
    """Инкрементальный (nightly) прогон: только новое с прошлого прогона.

    Водяной знак — метка времени последнего прогона в seen-store. Берём её как
    нижнюю границу `since`; на первом прогоне (метки нет) откатываемся на
    `lookback_days` (дефолт — `config.backfill_days`), чтобы засеять историю.
    После прогона сдвигаем водяной знак на момент старта. Seen-store служит
    backstop'ом дедупа: повторный прогон на тех же данных даёт ноль новых.
    """
    moment = now if now is not None else datetime.now(UTC)
    own_store = seen_store is None
    store = seen_store or SeenStore()
    try:
        watermark = store.get_watermark()
        if watermark is not None:
            since = watermark
        else:
            days = lookback_days if lookback_days is not None else config.backfill_days
            since = moment - timedelta(days=days)
        result = run_pipeline(
            config,
            since=since,
            output_path=output_path,
            seen_store=store,
            **kwargs,
        )
        store.set_watermark(moment)
        return result
    finally:
        if own_store:
            store.close()
