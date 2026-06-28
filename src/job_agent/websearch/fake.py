"""Детерминированный фейковый web-поиск для юнит-тестов (без сети).

Возвращает заранее заданные результаты (фиксированный список или функцию по
запросу) и записывает все запросы — стадии скоринга/контакт-поиска тестируются
на нём без обращения к реальному провайдеру.
"""

from __future__ import annotations

from collections.abc import Callable

from .base import Searcher, SearchResult

__all__ = ["FakeSearcher"]


class FakeSearcher(Searcher):
    """Фейк web-поиска с записью запросов.

    - `results` — список результатов (вернётся для любого запроса) либо функция
      `query -> list[SearchResult]`.
    """

    def __init__(
        self,
        results: list[SearchResult] | Callable[[str], list[SearchResult]] | None = None,
    ) -> None:
        self._results = results if results is not None else []
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.calls.append((query, max_results))
        if callable(self._results):
            out = self._results(query)
        else:
            out = self._results
        return list(out)[:max_results]

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_query(self) -> str | None:
        return self.calls[-1][0] if self.calls else None
