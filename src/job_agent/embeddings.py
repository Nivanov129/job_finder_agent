"""Эмбеддинги пре-фильтра (стадия 4): фиксированная локальная мультиязычная модель.

Модель фиксирована (`intfloat/multilingual-e5-large` через fastembed) и НЕ зависит от выбора
`scoring_engine` — пре-фильтр всегда локальный и детерминированный. Векторы
кэшируются за прогон по тексту: резюме треков и примеры карты эмбеддятся один
раз, повторные обращения берутся из кэша (тот же текст → тот же вектор без
повторного вызова модели). `cosine` — косинусная близость двух векторов.

Реальная модель грузится лениво и спрятана за фасадом (Protocol `EmbeddingModel`):
в тестах подменяется фейком, юнит-тесты в сеть не ходят и модель не качают.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

__all__ = ["MODEL_NAME", "EmbeddingModel", "Embedder", "cosine"]

# Фиксированная мультиязычная модель пре-фильтра. Не конфигурируется — инвариант
# продукта. fastembed не отдаёт bge-m3, поэтому зафиксирован поддерживаемый
# мультиязычный аналог (важно для русскоязычных резюме/вакансий).
MODEL_NAME = "intfloat/multilingual-e5-large"

Vector = tuple[float, ...]


@runtime_checkable
class EmbeddingModel(Protocol):
    """Фасад модели эмбеддингов (совместим с `fastembed.TextEmbedding`).

    `embed` принимает последовательность текстов и возвращает векторы в том же
    порядке. Реальная реализация — fastembed; в тестах — фейк.
    """

    def embed(self, texts: Sequence[str]) -> Iterable[Sequence[float]]: ...


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Косинусная близость двух векторов в диапазоне [-1, 1].

    Нулевой вектор (нет нормы) → 0.0. Разная длина — ошибка.
    """
    if len(a) != len(b):
        raise ValueError(f"несовпадающая размерность векторов: {len(a)} != {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class Embedder:
    """Кэширующая обёртка над фиксированной моделью эмбеддингов.

    Модель грузится лениво при первом эмбеддинге (или внедряется фейком в
    тестах). Кэш живёт на время прогона: один и тот же текст эмбеддится ровно
    один раз — это и детерминизм, и экономия (резюме треков / примеры карты
    повторно сравниваются со многими вакансиями).
    """

    def __init__(
        self, model: EmbeddingModel | None = None, *, model_name: str = MODEL_NAME
    ) -> None:
        self._model = model
        self.model_name = model_name
        self._cache: dict[str, Vector] = {}

    def _ensure_model(self) -> EmbeddingModel:
        if self._model is None:  # pragma: no cover - реальная загрузка не в юнит-тестах
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed(self, text: str) -> Vector:
        """Вектор одного текста (через кэш)."""
        return self.embed_many([text])[0]

    def embed_many(self, texts: Sequence[str]) -> list[Vector]:
        """Векторы для списка текстов, сохраняя порядок и пользуясь кэшем.

        В модель уходят только тексты, которых ещё нет в кэше, каждый один раз
        (внутри-пакетные дубли тоже схлопываются).
        """
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            model = self._ensure_model()
            for text, vector in zip(missing, model.embed(missing), strict=True):
                self._cache[text] = tuple(float(x) for x in vector)
        return [self._cache[t] for t in texts]

    def similarity(self, text_a: str, text_b: str) -> float:
        """Косинус между эмбеддингами двух текстов (оба через кэш)."""
        vectors = self.embed_many([text_a, text_b])
        return cosine(vectors[0], vectors[1])

    @property
    def cache_size(self) -> int:
        """Сколько уникальных текстов уже закэшировано за прогон."""
        return len(self._cache)
