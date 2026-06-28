"""Тесты калибровки порога пре-фильтра (Task 4.4).

Чистые функции распределения/рекомендации проверяются без сети и без модели.
`collect_best_sims`/`calibrate` гоняются на фейк-движке, фейк-эмбеддере и
стаб-коллекторе — офлайн, как и весь остальной пайплайн.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from job_agent.calibrate import (
    HistBin,
    calibrate,
    collect_best_sims,
    format_report,
    recommend_threshold,
    report_from_sims,
    summarize_sims,
)
from job_agent.config import Config
from job_agent.dedup import SeenStore
from job_agent.embeddings import Embedder
from job_agent.engines.base import Engine
from job_agent.models import RawPost

FAR_PAST = datetime(2000, 1, 1, tzinfo=UTC)


# --- чистые функции: распределение и рекомендация ---------------------------


def test_summarize_basic_stats_and_histogram():
    sims = [0.0, 0.5, 1.0]
    summary = summarize_sims(sims, bins=2)
    assert summary.count == 3
    assert summary.minimum == 0.0
    assert summary.maximum == 1.0
    assert summary.median == 0.5
    assert summary.mean == pytest.approx(0.5)
    # две корзины [0,0.5), [0.5,1.0]; значение 1.0 уходит в последнюю
    assert [b.count for b in summary.bins] == [1, 2]
    assert all(isinstance(b, HistBin) for b in summary.bins)
    # суммарный счёт корзин = числу значений
    assert sum(b.count for b in summary.bins) == 3


def test_summarize_even_count_median_is_average():
    summary = summarize_sims([0.2, 0.4, 0.6, 0.8], bins=4)
    assert summary.median == pytest.approx(0.5)


def test_summarize_empty_raises():
    with pytest.raises(ValueError, match="нет данных"):
        summarize_sims([])


def test_summarize_all_equal_single_bin():
    summary = summarize_sims([0.42, 0.42, 0.42], bins=5)
    assert summary.minimum == summary.maximum == 0.42
    assert len(summary.bins) == 1
    assert summary.bins[0].count == 3


def test_recommend_threshold_splits_bimodal():
    # Два чётких кластера: «шум» ~0.2 и «релевантные» ~0.8.
    sims = [0.18, 0.2, 0.22, 0.19, 0.21] + [0.78, 0.8, 0.82, 0.79, 0.81]
    thresh = recommend_threshold(sims, bins=20)
    # Граница Оцу должна лечь в долину между кластерами.
    assert 0.22 < thresh < 0.78


def test_recommend_threshold_degenerate_returns_value():
    assert recommend_threshold([0.5, 0.5, 0.5]) == pytest.approx(0.5)


def test_recommend_threshold_empty_raises():
    with pytest.raises(ValueError, match="нет данных"):
        recommend_threshold([])


def test_report_split_counts_match_recommendation():
    sims = [0.1, 0.15, 0.7, 0.75, 0.8]
    report = report_from_sims(sims, bins=10)
    assert report.finalists == sum(1 for s in sims if s >= report.recommended)
    assert report.cut == len(sims) - report.finalists
    assert report.finalists + report.cut == len(sims)


def test_format_report_contains_recommendation_and_histogram():
    report = report_from_sims([0.1, 0.12, 0.7, 0.72, 0.74], bins=5)
    text = format_report(report)
    assert "Рекомендованный min_sim" in text
    assert "Распределение best_sim" in text
    assert "min_sim" in text  # подсказка про запись в конфиг


# --- интеграция: сбор best_sim офлайн ---------------------------------------


class FakeModel:
    """Фейк-эмбеддинг: вектор по подстроке-метке в тексте, иначе ортогональ."""

    def __init__(self, table):
        self._table = table

    def embed(self, texts):
        for text in texts:
            yield self._vec(text)

    def _vec(self, text):
        for key, vec in self._table.items():
            if key in text:
                return list(vec)
        return [0.0, 1.0]


class NormalizeEngine(Engine):
    """Движок-заглушка нормализации: пост → одна вакансия с уникальным заголовком.

    Заголовок несёт метку близости (NEAR/FAR), чтобы фейк-эмбеддер дал заданный
    косинус против резюме.
    """

    def __init__(self):
        self.calls = 0

    def complete(self, prompt: str, *, web_search: bool = False) -> str:
        self.calls += 1
        n = self.calls
        # Чётные посты — близкие (NEAR), нечётные — далёкие (FAR).
        tag = "NEAR" if n % 2 == 0 else "FAR"
        return json.dumps(
            [
                {
                    "title": f"Product Manager {n}",
                    "company": f"Acme {n}",
                    "link_or_contact": "@hr",
                    "description": f"{tag} payload роль с метриками",
                }
            ]
        )


class StaticCollector:
    """Коллектор-стаб: отдаёт фиксированный набор постов независимо от `since`."""

    def __init__(self, count):
        self._count = count

    def fetch(self, since):
        return [
            RawPost(raw_text=f"вакансия {i}", source="stub", url=f"u{i}")
            for i in range(self._count)
        ]


def _config():
    data = {
        "version": 1,
        "tracks": [{"id": "main", "name": "Основной", "resume_path": "resume.md"}],
        "scoring_engine": "cli",
        "cli_tool": "claude",
        "output_mode": "table",
    }
    return Config.model_validate(data)


def _embedder():
    # Резюме коллинеарно NEAR (косинус 1), ортогонально FAR (косинус 0).
    table = {
        "RESUME": (1.0, 0.0),
        "NEAR": (1.0, 0.0),
        "FAR": (0.0, 1.0),
    }
    return Embedder(model=FakeModel(table))


def test_collect_best_sims_returns_full_distribution(tmp_path):
    config = _config()
    (tmp_path / "resume.md").write_text("RESUME", encoding="utf-8")

    sims = collect_best_sims(
        config,
        since=FAR_PAST,
        base_dir=tmp_path,
        engine=NormalizeEngine(),
        embedder=_embedder(),
        collectors=[StaticCollector(6)],
        seen_store=SeenStore(":memory:"),
    )

    # Все 6 вакансий прошли (роль-гейта нет): половина близких (~1), половина далёких (~0).
    assert len(sims) == 6
    assert sum(1 for s in sims if s > 0.9) == 3
    assert sum(1 for s in sims if s < 0.1) == 3


def test_calibrate_recommends_threshold_between_clusters(tmp_path):
    config = _config()
    (tmp_path / "resume.md").write_text("RESUME", encoding="utf-8")

    report = calibrate(
        config,
        days=14,
        bins=10,
        base_dir=tmp_path,
        engine=NormalizeEngine(),
        embedder=_embedder(),
        collectors=[StaticCollector(6)],
        seen_store=SeenStore(":memory:"),
    )

    assert report.summary.count == 6
    # Порог между кластерами 0 и 1 → ровно 3 финалиста.
    assert 0.0 < report.recommended < 1.0
    assert report.finalists == 3
    assert report.cut == 3
