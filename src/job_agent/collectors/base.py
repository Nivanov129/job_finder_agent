"""Общий интерфейс коллектора (стадия 1 — сбор).

Любой источник (TG публичный/приватный, агрегаторы) реализует `fetch(since)` и
возвращает `list[RawPost]`. Сетевой код и парсинг живут внутри адаптера, наружу
торчит только этот контракт.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import RawPost

__all__ = ["Collector"]


class Collector(ABC):
    """Источник сырых постов."""

    @abstractmethod
    def fetch(self, since: datetime) -> list[RawPost]:
        """Вернуть посты не старше `since` (по дате поста, если она известна)."""
        raise NotImplementedError
