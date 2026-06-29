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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .collectors.base import Collector
from .collectors.habr import HabrCollector
from .collectors.linkedin import LinkedinSearchCollector
from .collectors.telegram_private import (
    creds_from_env,
    creds_present,
    make_private_collector,
)
from .collectors.telegram_public import TelegramPublicCollector
from .collectors.vseti import VsetiCollector
from .config import Config
from .dedup import SeenStore
from .embeddings import Embedder
from .engines import make_engine
from .engines.base import Engine
from .enrich.contacts import find_contacts
from .enrich.cover import write_cover_letter
from .enrich.investigator import investigate_contacts
from .models import EnrichedResult, RawPost
from .normalize import normalize_posts
from .output.xlsx import write_xlsx
from .prefilter import DEFAULT_LIMIT, DEFAULT_MIN_SIM, MapExample, prefilter_and_route
from .scoring import score_routed
from .titlefilter import derive_titles, filter_posts_by_titles
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
    habr_fetcher=None,
    linkedin_searcher: Searcher | None = None,
) -> list[Collector]:
    """Собрать коллекторы по конфигу (стадия 1). Фетчеры инъектируются в тестах.

    Публичные TG-каналы — через `t.me/s/`; приватные — Telethon (только при
    creds или инъекции fetcher); агрегаторы — при `use_aggregators`: vseti.app и
    career.habr.com (getmatch отключён — их публичный API больше не доступен).
    """
    collectors: list[Collector] = []

    public_handles = [c.handle for c in config.tg_channels if not c.private]
    if public_handles:
        collectors.append(TelegramPublicCollector(public_handles, fetcher=public_fetcher))

    private_handles = [c.handle for c in config.tg_channels if c.private]
    if private_handles:
        # Секреты Telethon (api_id/api_hash/session) — из .env; конфиг как фолбэк.
        creds = config.telethon_creds
        if not creds_present(creds):
            creds = creds_from_env()
        private = make_private_collector(
            private_handles, creds, fetcher=private_fetcher
        )
        if private is not None:
            collectors.append(private)

    if config.use_aggregators:
        collectors.append(VsetiCollector(fetcher=vseti_fetcher))
        collectors.append(HabrCollector(fetcher=habr_fetcher))

    if config.use_linkedin:
        # Роли для дорков — допустимые роли треков (из резюме), иначе глобальные.
        roles = [r for t in config.tracks for r in (t.role_gate or [])]
        if not roles:
            roles = list(config.global_role_gate)
        searcher = linkedin_searcher
        if searcher is None:
            try:
                searcher = make_searcher(config)
            except Exception as exc:  # web-поиск не настроен — без LinkedIn
                logger.warning("LinkedIn-источник пропущен: %s", exc)
                searcher = None
        if searcher is not None and roles:
            collectors.append(LinkedinSearchCollector(roles, searcher))

    return collectors


def _derive_all_titles(engine: Engine, track_resumes: dict[str, str]) -> list[str]:
    """Названия должностей из всех резюме треков (по уникальному резюме), без дублей."""
    titles: list[str] = []
    seen_resumes: set[str] = set()
    for resume in track_resumes.values():
        key = resume.strip()[:200]
        if not key or key in seen_resumes:
            continue
        seen_resumes.add(key)
        try:
            titles.extend(derive_titles(engine, resume))
        except Exception as exc:
            logger.warning("вывод названий должности пропущен: %s", str(exc)[:120])
    out: list[str] = []
    seen: set[str] = set()
    for t in titles:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _dedupe_raw_posts(posts: list[RawPost]) -> list[RawPost]:
    """Убрать точные повторы постов по нормализованному тексту (первый — остаётся)."""
    seen: set[str] = set()
    out: list[RawPost] = []
    for post in posts:
        key = " ".join(post.raw_text.split()).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(post)
    return out


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
    on_progress: Callable[[str, dict[str, int]], None] | None = None,
    on_result: Callable[[EnrichedResult], None] | None = None,
    on_item: Callable[[dict], None] | None = None,
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

    def _report(stage: str, **counts: int) -> None:
        if on_progress is not None:
            try:
                on_progress(stage, counts)
            except Exception:  # pragma: no cover - прогресс не роняет прогон
                pass

    def _emit(phase: str, title: str, company: str | None, src: str | None) -> None:
        """Живая лента: что AI читает/оценивает прямо сейчас (реальные посты)."""
        if on_item is not None:
            try:
                on_item({
                    "phase": phase,
                    "role": title,
                    "company": company or "",
                    "src": src or "",
                })
            except Exception:  # pragma: no cover - лента не роняет прогон
                pass

    own_store = seen_store is None
    store = seen_store or SeenStore()
    try:
        # 1. Сбор. Источники изолированы: поломка одного адаптера (сменилась
        # вёрстка/API, сеть) логируется и не валит прогон — собираем по остальным.
        posts = []
        for collector in collectors:
            try:
                posts.extend(collector.fetch(since))
            except Exception as exc:
                logger.warning(
                    "источник %s пропущен: %s",
                    type(collector).__name__,
                    exc,
                )
        collected = len(posts)

        # Дедуп постов по тексту: один и тот же пост из нескольких каналов
        # нормализуем один раз (экономия вызовов AI). Дедуп по смыслу
        # (title+company из разных каналов) — позже в SeenStore.
        posts = _dedupe_raw_posts(posts)
        if len(posts) < collected:
            logger.info("повторы постов убраны: %d → %d", collected, len(posts))

        # Резюме треков нужны и для грубого фильтра, и для пре-фильтра — грузим раз.
        track_resumes = load_track_resumes(config, base)

        # 1.5 Грубый фильтр по названию должности (из резюме) ДО нормализации:
        # отсекаем заведомо нерелевантные посты, чтобы не гонять дорогой AI зря.
        if config.title_prefilter and posts:
            titles = _derive_all_titles(engine, track_resumes)
            if titles:
                before = len(posts)
                kept = filter_posts_by_titles(posts, titles)
                # Защита: если фильтр выкосил всё (названия не совпали ни с одним
                # постом) — он явно слишком узкий, не отсекаем, идём как есть.
                if kept:
                    posts = kept
                    logger.info("фильтр по названию: %d → %d", before, len(posts))
                else:
                    logger.warning(
                        "фильтр по названию ничего не оставил (%d постов) — пропускаю",
                        before,
                    )
        to_normalize = len(posts)
        _report("normalize", collected=collected, to_normalize=to_normalize)

        # 2. Нормализация (параллельно, изоляция по посту).
        done = {"n": 0}

        def _tick(post: RawPost, vacs: list) -> None:
            done["n"] += 1
            _report(
                "normalize", collected=collected,
                to_normalize=to_normalize, normalized=done["n"],
            )
            # Живая лента: реальные вакансии, которые AI только что вычитал из поста.
            for vac in vacs:
                _emit("read", vac.title, vac.company, vac.source or post.source)

        vacancies = normalize_posts(
            posts,
            engine,
            output_lang=config.output_lang,
            workers=config.parallelism,
            on_each=_tick,
        )

        # 3. Дедуп (кросс-источник + внутрипрогонный), помечаем виденными.
        fresh = store.filter_new(vacancies)

        # 4. Пре-фильтр + роутинг.
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
        _report("score", collected=collected, after_filter=after_filter)

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

        scored = {"n": 0}

        def _score_one(rv) -> EnrichedResult | None:
            # Лента: показываем, какую вакансию AI сейчас оценивает (два процента).
            _emit("score", rv.vacancy.title, rv.vacancy.company, rv.vacancy.source)
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
                return None
            # 6. Обогащение: сопроводительное (гейт по порогу+шаблон) + опц. контакты.
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
            track_name = track.name if track is not None else score.track
            contacts = None
            if config.enable_contacts and contact_searcher is not None:
                # Изоляция обогащения: сбой контактов (недоступный web-поиск и т.п.)
                # НЕ должен выбрасывать уже посчитанную вакансию из выгрузки.
                try:
                    contacts = find_contacts(
                        rv.vacancy,
                        engine,
                        contact_searcher,
                        track_name=track_name,
                        enable_contacts=True,
                        output_lang=config.output_lang,
                    )
                except Exception as exc:
                    logger.warning(
                        "контакты для «%s» пропущены: %s",
                        rv.vacancy.title,
                        str(exc)[:160],
                    )
            investigation = None
            if config.enable_contact_investigator:
                # Доп-движок контактов «с именем» — тоже изолирован.
                try:
                    investigation = investigate_contacts(
                        rv.vacancy,
                        engine,
                        track_name=track_name,
                        enable_investigator=True,
                        output_lang=config.output_lang,
                    )
                except Exception as exc:
                    logger.warning(
                        "инвестигатор контактов для «%s» пропущен: %s",
                        rv.vacancy.title,
                        str(exc)[:160],
                    )
            return EnrichedResult(
                vacancy=rv.vacancy, score=score, cover_letter=cover_letter,
                contacts=contacts, investigation=investigation,
            )

        def _run_score(rv) -> EnrichedResult | None:
            # Изоляция: сбой по одному финалисту не валит остальной скоринг.
            try:
                result = _score_one(rv)
            except Exception as exc:
                logger.warning("скоринг финалиста пропущен: %s", str(exc)[:160])
                result = None
            scored["n"] += 1
            _report("score", collected=collected, after_filter=after_filter,
                    scored=scored["n"])
            if result is not None and on_result is not None:
                try:
                    on_result(result)
                except Exception:  # pragma: no cover - стриминг не роняет прогон
                    pass
            return result

        # Скоринг параллельно (ex.map сохраняет порядок); финалистов немного.
        if config.parallelism > 1 and len(routed) > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=min(config.parallelism, len(routed))) as ex:
                results = [r for r in ex.map(_run_score, routed) if r is not None]
        else:
            results = [r for r in (_run_score(rv) for rv in routed) if r is not None]

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
