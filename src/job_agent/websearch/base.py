"""Интерфейс web-поиска.

Стадии скоринга (анализ компании) и контакт-поиска работают только через этот
контракт. Конкретные адаптеры (`searxng`, `serp`) живут отдельными модулями за
фасадом HTTP; сетевые вызовы и секреты наружу не торчат.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict

__all__ = ["SearchResult", "Searcher"]


class SearchResult(BaseModel):
    """Один результат web-поиска: заголовок, ссылка, краткий сниппет."""

    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    snippet: str = ""


class Searcher(ABC):
    """Web-поиск: запрос → список результатов."""

    @abstractmethod
    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Выполнить запрос и вернуть до `max_results` результатов.

        Реализация не падает на пустом/кривом ответе провайдера — возвращает
        пустой список. Парсинг найденного — на вызывающей стадии.
        """
        raise NotImplementedError
