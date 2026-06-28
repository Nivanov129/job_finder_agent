"""Пре-фильтр и роутинг (стадия 4) — код, не LLM (`prompts/prefilter-routing.md`).

Локальные эмбеддинги (`embeddings.Embedder`, фиксированная bge-m3) решают, к какому
направлению относится вакансия и стоит ли её вообще скорить:

1. Косинус резюме каждого трека ↔ текст вакансии → `best_track` (argmax).
2. Гейт по роли: токены `track.role_gate`, иначе глобальный `global_role_gate`,
   матчатся по заголовку вакансии; не прошла — отсекается.
3. Порог близости `min_sim` (мягкий дефолт, конфигурируем — калибруется на backfill).
4. Предварительный `map_fit_pre` по примерам карты поиска (тег `track_id` + общие).
5. Опц. мульти-трек: `candidate_tracks` — треки в пределах `multi_track_delta` от
   лучшего (только при `multi_track=True`).
6. Отсечение до `limit` финалистов (топ по `best_sim`).

N=1 — тривиальный роутинг: единственный трек всегда лучший, ветвления нет. Стадия
чисто локальная и детерминированная; тексты резюме/карты подаёт оркестратор
(Task 1.13) — чтение PDF и т.п. сюда не затаскиваем.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .config import Track
from .embeddings import Embedder
from .models import RoutedVacancy, Vacancy

__all__ = [
    "DEFAULT_MIN_SIM",
    "DEFAULT_LIMIT",
    "MapExample",
    "prefilter_and_route",
]

# Мягкий дефолт порога близости: не зафиксирован числом, калибруется на backfill
# (Task 4.4). До тех пор — конфигурируемый дефолт, чтобы стадия работала.
DEFAULT_MIN_SIM = 0.30

# Сколько финалистов оставить под скоринг (стадия 5 — дорогая, режем заранее).
DEFAULT_LIMIT = 20

# Пример карты поиска: (текст, track_id|None). None — общий эталон по всем трекам.
MapExample = tuple[str, str | None]


def _vacancy_text(vacancy: Vacancy) -> str:
    """Текст вакансии для эмбеддинга: заголовок + компания + описание."""
    parts = [vacancy.title]
    if vacancy.company:
        parts.append(vacancy.company)
    if vacancy.description:
        parts.append(vacancy.description)
    return "\n".join(parts)


def _passes_role_gate(title: str, gate: Sequence[str]) -> bool:
    """Пустой гейт пропускает всех; иначе нужен хотя бы один токен в заголовке."""
    if not gate:
        return True
    haystack = title.lower()
    return any(token.lower() in haystack for token in gate)


def _sim_to_percent(sim: float) -> int:
    """Косинус [-1, 1] → процент [0, 100] (отрицательное → 0)."""
    return max(0, min(100, round(sim * 100)))


def _map_fit_pre(
    vacancy_text: str,
    best_track: str,
    examples: Sequence[MapExample],
    embedder: Embedder,
) -> int:
    """Предварительный процент карты: макс. косинус по примерам трека + общим.

    Берём примеры, помеченные `best_track`, и общие (без `track_id`). Нет
    подходящих примеров → 0 (настоящий `map_fit` посчитает скоринг).
    """
    relevant = [
        text for text, track_id in examples if track_id in (None, best_track)
    ]
    if not relevant:
        return 0
    best = max(embedder.similarity(vacancy_text, text) for text in relevant)
    return _sim_to_percent(best)


def prefilter_and_route(
    vacancies: Sequence[Vacancy],
    tracks: Sequence[Track],
    *,
    embedder: Embedder,
    track_resumes: Mapping[str, str],
    search_map_examples: Sequence[MapExample] = (),
    global_role_gate: Sequence[str] = (),
    multi_track: bool = False,
    multi_track_delta: float = 0.05,
    min_sim: float = DEFAULT_MIN_SIM,
    limit: int = DEFAULT_LIMIT,
) -> list[RoutedVacancy]:
    """Отроутить вакансии по трекам и отсечь до финалистов.

    `track_resumes` — id трека → текст резюме (оркестратор грузит из `resume_path`).
    Возвращает выживших, отсортированных по `best_sim` убыв., не более `limit`.
    """
    if not tracks:
        raise ValueError("prefilter_and_route: нужен хотя бы один трек")

    by_id = {track.id: track for track in tracks}
    missing = [t.id for t in tracks if t.id not in track_resumes]
    if missing:
        raise ValueError(f"нет текста резюме для треков: {', '.join(missing)}")

    routed: list[RoutedVacancy] = []
    for vacancy in vacancies:
        vac_text = _vacancy_text(vacancy)

        # Косинус против резюме каждого трека → лучший.
        sims = {
            track.id: embedder.similarity(vac_text, track_resumes[track.id])
            for track in tracks
        }
        best_track = max(sims, key=lambda tid: sims[tid])
        best_sim = sims[best_track]

        # Гейт по роли: трек-специфичный, иначе глобальный.
        gate = by_id[best_track].role_gate or global_role_gate
        if not _passes_role_gate(vacancy.title, gate):
            continue

        # Порог близости.
        if best_sim < min_sim:
            continue

        # Опц. мульти-трек: треки в пределах дельты от лучшего.
        if multi_track:
            candidate_tracks = sorted(
                (tid for tid, sim in sims.items() if best_sim - sim <= multi_track_delta),
                key=lambda tid: sims[tid],
                reverse=True,
            )
        else:
            candidate_tracks = []

        routed.append(
            RoutedVacancy(
                vacancy=vacancy,
                best_track=best_track,
                best_sim=best_sim,
                map_fit_pre=_map_fit_pre(
                    vac_text, best_track, search_map_examples, embedder
                ),
                candidate_tracks=candidate_tracks,
            )
        )

    routed.sort(key=lambda r: r.best_sim, reverse=True)
    return routed[:limit]
