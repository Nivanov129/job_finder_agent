"""Тесты пре-фильтра и роутинга (стадия 4): роутинг, гейт, мульти-трек, N=1.

Эмбеддинги мокаются детерминированной фейк-моделью — юнит-тесты в сеть не ходят
и модель не качают. Векторы подобраны так, что косинус задаёт ожидаемый трек.
"""

from __future__ import annotations

import pytest

from job_agent.config import Track
from job_agent.embeddings import Embedder
from job_agent.models import Vacancy
from job_agent.prefilter import (
    DEFAULT_LIMIT,
    DEFAULT_MIN_SIM,
    prefilter_and_route,
    route_by_role_only,
)


def test_route_by_role_only_no_embeddings() -> None:
    # Без эмбеддингов: роутинг по role_gate, без порога близости.
    tracks = [_track("a", role_gate=["Менеджер продукта"])]
    kept = _vac("Менеджер по продукту", "VAC")  # проходит роль (по словам)
    dropped = _vac("Бэкенд-разработчик", "VAC")  # нет такой роли
    routed = route_by_role_only([kept, dropped], tracks)
    assert [r.vacancy.title for r in routed] == ["Менеджер по продукту"]
    assert routed[0].best_track == "a" and routed[0].map_fit_pre == 0


class FakeModel:
    """Фейк-модель: текст → вектор по таблице (точное совпадение по подстроке).

    Берём первый ключ таблицы, входящий в текст; так вакансия и резюме одного
    трека получают коллинеарные векторы (косинус ~1), чужого — ортогональные.
    """

    def __init__(self, table: dict[str, list[float]]) -> None:
        self._table = table

    def embed(self, texts):
        for text in texts:
            yield list(self._vec(text))

    def _vec(self, text: str) -> list[float]:
        for key, vec in self._table.items():
            if key in text:
                return vec
        return [0.0, 0.0, 0.0]


def _emb(table: dict[str, list[float]]) -> Embedder:
    return Embedder(model=FakeModel(table))


def _track(track_id: str, **kw) -> Track:
    return Track(id=track_id, name=track_id, resume_path=f"./{track_id}.pdf", **kw)


def _vac(title: str, description: str = "") -> Vacancy:
    return Vacancy(title=title, description=description)


def test_routes_to_nearest_track_by_cosine():
    table = {
        "RES_A": [1.0, 0.0, 0.0],
        "RES_B": [0.0, 1.0, 0.0],
        "VAC_A": [1.0, 0.0, 0.0],
    }
    tracks = [_track("a"), _track("b")]
    resumes = {"a": "RES_A", "b": "RES_B"}
    vac = _vac("Engineer", "VAC_A payload")

    routed = prefilter_and_route(
        [vac], tracks, embedder=_emb(table), track_resumes=resumes
    )

    assert len(routed) == 1
    assert routed[0].best_track == "a"
    assert routed[0].best_sim == pytest.approx(1.0)


def test_role_gate_drops_non_matching_title():
    table = {"RES_A": [1.0, 0.0, 0.0], "VAC_A": [1.0, 0.0, 0.0]}
    tracks = [_track("a", role_gate=["Product Manager"])]
    resumes = {"a": "RES_A"}

    kept = _vac("Senior Product Manager", "VAC_A")
    dropped = _vac("Backend Engineer", "VAC_A")

    routed = prefilter_and_route(
        [kept, dropped], tracks, embedder=_emb(table), track_resumes=resumes
    )

    assert [r.vacancy.title for r in routed] == ["Senior Product Manager"]


def test_role_gate_matches_across_word_order_and_endings():
    # «Менеджер по продукту» должен пройти роль «Менеджер продукта»
    # (другой порядок слов + окончание) — гейт пословный, стем-устойчивый.
    table = {"RES_A": [1.0, 0.0, 0.0], "VAC_A": [1.0, 0.0, 0.0]}
    tracks = [_track("a", role_gate=["Менеджер продукта", "Директор продукта"])]
    resumes = {"a": "RES_A"}

    kept_a = _vac("Менеджер по продукту", "VAC_A")   # порядок слов + окончание
    kept_b = _vac("Директор по продукту", "VAC_A")
    dropped = _vac("Бизнес-аналитик", "VAC_A")       # нет роли с такими словами

    routed = prefilter_and_route(
        [kept_a, kept_b, dropped], tracks, embedder=_emb(table), track_resumes=resumes
    )
    titles = [r.vacancy.title for r in routed]
    assert "Менеджер по продукту" in titles
    assert "Директор по продукту" in titles
    assert "Бизнес-аналитик" not in titles


def test_global_role_gate_used_when_track_has_none():
    table = {"RES_A": [1.0, 0.0, 0.0], "VAC_A": [1.0, 0.0, 0.0]}
    tracks = [_track("a")]  # без role_gate → берётся глобальный
    resumes = {"a": "RES_A"}

    routed = prefilter_and_route(
        [_vac("Data Analyst", "VAC_A")],
        tracks,
        embedder=_emb(table),
        track_resumes=resumes,
        global_role_gate=["Manager"],
    )

    assert routed == []  # «Data Analyst» не содержит «Manager»


def test_min_sim_threshold_filters_far_vacancies():
    table = {
        "RES_A": [1.0, 0.0, 0.0],
        "VAC_FAR": [0.0, 1.0, 0.0],  # ортогонально резюме → косинус 0
    }
    tracks = [_track("a")]
    resumes = {"a": "RES_A"}

    routed = prefilter_and_route(
        [_vac("Engineer", "VAC_FAR")],
        tracks,
        embedder=_emb(table),
        track_resumes=resumes,
        min_sim=0.5,
    )

    assert routed == []


def test_map_fit_pre_from_relevant_examples():
    table = {
        "RES_A": [1.0, 0.0, 0.0],
        "VAC_A": [1.0, 0.0, 0.0],
        "MAP_A": [1.0, 0.0, 0.0],  # коллинеарно вакансии → карта ~100
    }
    tracks = [_track("a")]
    resumes = {"a": "RES_A"}

    routed = prefilter_and_route(
        [_vac("Engineer", "VAC_A")],
        tracks,
        embedder=_emb(table),
        track_resumes=resumes,
        search_map_examples=[("MAP_A example", "a"), ("MAP_OTHER", "b")],
    )

    assert routed[0].map_fit_pre == 100


def test_map_fit_pre_zero_without_examples():
    table = {"RES_A": [1.0, 0.0, 0.0], "VAC_A": [1.0, 0.0, 0.0]}
    tracks = [_track("a")]
    routed = prefilter_and_route(
        [_vac("Engineer", "VAC_A")],
        tracks,
        embedder=_emb(table),
        track_resumes={"a": "RES_A"},
    )
    assert routed[0].map_fit_pre == 0


def test_multi_track_collects_candidates_within_delta():
    # Вакансия близка к обоим трекам (одинаковый вектор) → оба в пределах дельты.
    table = {
        "RES_A": [1.0, 0.0, 0.0],
        "RES_B": [1.0, 0.0, 0.0],
        "VAC": [1.0, 0.0, 0.0],
    }
    tracks = [_track("a"), _track("b")]
    resumes = {"a": "RES_A", "b": "RES_B"}

    routed = prefilter_and_route(
        [_vac("Engineer", "VAC")],
        tracks,
        embedder=_emb(table),
        track_resumes=resumes,
        multi_track=True,
        multi_track_delta=0.05,
    )

    assert sorted(routed[0].candidate_tracks) == ["a", "b"]


def test_multi_track_disabled_leaves_candidates_empty():
    table = {"RES_A": [1.0, 0.0, 0.0], "RES_B": [1.0, 0.0, 0.0], "VAC": [1.0, 0.0, 0.0]}
    tracks = [_track("a"), _track("b")]
    routed = prefilter_and_route(
        [_vac("Engineer", "VAC")],
        tracks,
        embedder=_emb(table),
        track_resumes={"a": "RES_A", "b": "RES_B"},
        multi_track=False,
    )
    assert routed[0].candidate_tracks == []


def test_single_track_trivial_routing():
    table = {"RES_A": [1.0, 0.0, 0.0], "VAC_A": [1.0, 0.0, 0.0]}
    tracks = [_track("solo")]
    routed = prefilter_and_route(
        [_vac("Engineer", "VAC_A")],
        tracks,
        embedder=_emb(table),
        track_resumes={"solo": "RES_A"},
    )
    assert len(routed) == 1
    assert routed[0].best_track == "solo"
    assert routed[0].candidate_tracks == []


def test_sorted_by_sim_and_limit():
    table = {
        "RES_A": [1.0, 0.0, 0.0],
        "VAC_HI": [1.0, 0.0, 0.0],  # косинус 1.0
        "VAC_MID": [1.0, 1.0, 0.0],  # косинус ~0.707
    }
    tracks = [_track("a")]
    resumes = {"a": "RES_A"}
    vacs = [_vac("Eng mid", "VAC_MID"), _vac("Eng hi", "VAC_HI")]

    routed = prefilter_and_route(
        vacs, tracks, embedder=_emb(table), track_resumes=resumes, limit=1
    )

    assert len(routed) == 1
    assert routed[0].vacancy.title == "Eng hi"  # выше косинус → первым, лимит режет


def test_missing_resume_raises():
    tracks = [_track("a")]
    with pytest.raises(ValueError, match="резюме"):
        prefilter_and_route(
            [_vac("Eng", "x")],
            tracks,
            embedder=_emb({}),
            track_resumes={},
        )


def test_no_tracks_raises():
    with pytest.raises(ValueError, match="трек"):
        prefilter_and_route(
            [_vac("Eng", "x")], [], embedder=_emb({}), track_resumes={}
        )


def test_defaults_exposed():
    assert DEFAULT_MIN_SIM == 0.30
    assert DEFAULT_LIMIT == 20
