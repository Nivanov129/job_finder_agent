"""Тесты LinkedIn-коллектора: дорк по ролям через фейк-поиск, без сети."""

from __future__ import annotations

from datetime import UTC, datetime

from job_agent.collectors.linkedin import (
    DEFAULT_DOMAINS,
    LinkedinSearchCollector,
    build_dork,
)
from job_agent.websearch.base import Searcher, SearchResult


class FakeSearcher(Searcher):
    """Фейк: запоминает запросы, отдаёт заранее заданную выдачу по роли."""

    def __init__(self, table: dict[str, list[SearchResult]]) -> None:
        self.table = table
        self.queries: list[str] = []

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        for key, results in self.table.items():
            if key in query:
                return results[:max_results]
        return []


def test_build_dork_has_quotes_filter_and_both_sites():
    dork = build_dork("Product Manager", DEFAULT_DOMAINS)
    assert '"Product Manager"' in dork
    assert '"Vacancy"' in dork
    assert '-intitle:"vacancies"' in dork
    assert "site:ru.linkedin.com/" in dork
    assert "site:www.linkedin.com/" in dork


def test_collects_posts_from_search_and_dedupes_by_url():
    lk = "https://ru.linkedin.com/jobs/"
    table = {
        "Product Manager": [
            SearchResult(title="PM at Avito", url=lk + "1", snippet="Vacancy"),
            SearchResult(title="PM dup", url=lk + "1", snippet="dup"),
            SearchResult(title="PM at Ozon", url=lk + "2", snippet="hiring"),
        ],
        "Менеджер продукта": [
            SearchResult(title="Менеджер продукта, Сбер", url=lk + "3"),
        ],
    }
    searcher = FakeSearcher(table)
    collector = LinkedinSearchCollector(
        ["Product Manager", "Менеджер продукта"], searcher
    )

    posts = collector.fetch(datetime(2026, 6, 1, tzinfo=UTC))

    # дубль по url убран → 3 уникальных поста, источник linkedin
    assert len(posts) == 3
    assert {p.source for p in posts} == {"linkedin"}
    assert "PM at Avito" in posts[0].raw_text
    assert len(searcher.queries) == 2  # один дорк на роль


def test_one_role_failure_does_not_break_others():
    class Boom(Searcher):
        def search(self, query: str, *, max_results: int = 5):
            if "Bad" in query:
                raise RuntimeError("searxng down")
            return [SearchResult(title="ok", url="https://ru.linkedin.com/jobs/9")]

    collector = LinkedinSearchCollector(["Bad", "Good"], Boom())
    posts = collector.fetch(datetime(2026, 6, 1, tzinfo=UTC))
    assert len(posts) == 1  # «Bad» упал и пропущен, «Good» собрал


def test_drops_aggregate_listings_and_stale():
    table = {
        "Product Manager": [
            # конкретная вакансия — оставить
            SearchResult(
                title="Product Manager, Avito · 3 июн. 2026 г.",
                url="https://ru.linkedin.com/posts/abc-activity-123",
                snippet="#vacancy #hiring",
            ),
            # агрегатный листинг по url — выкинуть
            SearchResult(
                title="Product Manager jobs",
                url="https://www.linkedin.com/jobs/product-manager-jobs",
            ),
            # агрегатный листинг по заголовку — выкинуть
            SearchResult(
                title="140,000+ Product Manager jobs in United States",
                url="https://www.linkedin.com/jobs/view/aggregate",
            ),
            # старая дата (раньше периода) — выкинуть
            SearchResult(
                title="Product Manager · 6 окт. 2024 г.",
                url="https://ru.linkedin.com/posts/old-activity-9",
                snippet="hiring",
            ),
        ]
    }
    col = LinkedinSearchCollector(["Product Manager"], FakeSearcher(table))
    posts = col.fetch(datetime(2026, 6, 1, tzinfo=UTC))
    urls = [p.url for p in posts]
    assert urls == ["https://ru.linkedin.com/posts/abc-activity-123"]
    assert posts[0].date == datetime(2026, 6, 3, tzinfo=UTC)


def test_caps_number_of_roles():
    searcher = FakeSearcher({})
    roles = [f"Role {i}" for i in range(20)]
    collector = LinkedinSearchCollector(roles, searcher, max_roles=8)
    collector.fetch(datetime(2026, 6, 1, tzinfo=UTC))
    assert len(searcher.queries) == 8
