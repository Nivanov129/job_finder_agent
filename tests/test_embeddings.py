"""Тесты эмбеддингов: cosine + детерминизм кэша на мокнутой модели (без сети)."""

from __future__ import annotations

import math

import pytest

from job_agent.embeddings import MODEL_NAME, Embedder, cosine


class FakeModel:
    """Детерминированная фейк-модель: текст → стабильный вектор, со счётчиком.

    `calls` — сколько раз дёрнули `embed`; `embedded` — все тексты, ушедшие в
    модель (для проверки, что кэш не пускает повторы).
    """

    def __init__(self) -> None:
        self.calls = 0
        self.embedded: list[str] = []
        self._table = {
            "alpha": [1.0, 0.0, 0.0],
            "beta": [0.0, 1.0, 0.0],
            "alpha-ish": [2.0, 0.0, 0.0],
        }

    def embed(self, texts):
        self.calls += 1
        for text in texts:
            self.embedded.append(text)
            yield list(self._table[text])


def test_cosine_basics():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    # Коллинеарные разной длины → 1.0 (нормируется).
    assert cosine([1.0, 0.0, 0.0], [2.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_cosine_zero_vector_is_zero():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_dimension_mismatch_raises():
    with pytest.raises(ValueError):
        cosine([1.0, 0.0], [1.0])


def test_cache_is_deterministic_and_hits_model_once():
    model = FakeModel()
    emb = Embedder(model=model)

    first = emb.embed("alpha")
    second = emb.embed("alpha")

    assert first == second  # один текст → один и тот же вектор
    assert model.embedded == ["alpha"]  # модель спросили про «alpha» лишь раз
    assert emb.cache_size == 1


def test_embed_many_dedups_within_and_across_calls():
    model = FakeModel()
    emb = Embedder(model=model)

    out = emb.embed_many(["alpha", "beta", "alpha"])
    assert out[0] == out[2]  # порядок сохранён, дубль из кэша
    assert sorted(model.embedded) == ["alpha", "beta"]  # каждый уникальный — раз

    emb.embed_many(["beta", "alpha"])  # всё уже в кэше
    assert sorted(model.embedded) == ["alpha", "beta"]  # модель не дёргали повторно


def test_similarity_uses_cache():
    model = FakeModel()
    emb = Embedder(model=model)

    sim = emb.similarity("alpha", "alpha-ish")
    assert sim == pytest.approx(1.0)  # коллинеарны
    assert math.isfinite(sim)
    assert emb.cache_size == 2


def test_fixed_model_name():
    assert MODEL_NAME == "BAAI/bge-m3"
    assert Embedder().model_name == MODEL_NAME
