"""Тесты коллектора карьерных сайтов: дорк по ролям через фейк-поиск, без сети."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_agent.collectors.career_sites import (
    CareerSiteCollector,
    build_query,
    normalize_site,
)
from job_agent.websearch.base import Searcher, SearchResult

SINCE = datetime(2020, 1, 1, tzinfo=UTC)


class FakeSearcher(Searcher):
    """Фейк: запоминает запросы, отдаёт заранее заданную выдачу по подстроке."""

    def __init__(self, table: dict[str, list[SearchResult]]) -> None:
        self.table = table
        self.queries: list[str] = []

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        for key, results in self.table.items():
            if key in query:
                return results[:max_results]
        return []


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("career.ozon.ru", "career.ozon.ru"),
        ("https://career.ozon.ru/", "career.ozon.ru"),  # хвостовой / срезан
        ("https://yandex.ru/jobs", "yandex.ru/jobs"),  # путь раздела сохранён
        ("https://www.tbank.ru/career/", "tbank.ru/career"),  # www убран, путь есть
        ("www.jobs.yandex.ru", "jobs.yandex.ru"),
        ("  HH.RU/  ", "hh.ru"),
        ("", ""),
    ],
)
def test_normalize_site(raw: str, expected: str) -> None:
    assert normalize_site(raw) == expected


def test_build_query_quotes_role_and_ors_sites() -> None:
    q = build_query("Product Manager", ["career.ozon.ru", "yandex.ru/jobs"])
    assert q == '"Product Manager" (site:career.ozon.ru OR site:yandex.ru/jobs)'


def test_build_query_without_sites_is_just_role() -> None:
    assert build_query("Data Scientist", []) == '"Data Scientist"'


def test_fetch_builds_posts_and_dedupes_by_url() -> None:
    site = "https://career.ozon.ru/vacancy/"
    searcher = FakeSearcher(
        {
            "Product Manager": [
                SearchResult(title="PM в Ozon", url=site + "1", snippet="ищем продакта"),
                SearchResult(title="дубль", url=site + "1", snippet="тот же url"),
                SearchResult(title="Senior PM", url=site + "2", snippet=""),
            ]
        }
    )
    posts = CareerSiteCollector(
        ["Product Manager"], searcher, ["career.ozon.ru"]
    ).fetch(SINCE)
    assert [p.url for p in posts] == [site + "1", site + "2"]
    assert all(p.source == "career_site" for p in posts)
    assert "PM в Ozon" in posts[0].raw_text
    # дорк ушёл с доменом и ролью
    assert searcher.queries == ['"Product Manager" (site:career.ozon.ru)']


def test_fetch_drops_site_root_results() -> None:
    searcher = FakeSearcher(
        {
            "PM": [
                SearchResult(title="главная", url="https://career.ozon.ru/", snippet="о нас"),
                SearchResult(title="вакансия", url="https://career.ozon.ru/vacancy/9", snippet="x"),
            ]
        }
    )
    posts = CareerSiteCollector(["PM"], searcher, ["career.ozon.ru"]).fetch(SINCE)
    assert [p.url for p in posts] == ["https://career.ozon.ru/vacancy/9"]


def test_fetch_empty_without_roles_or_sites() -> None:
    searcher = FakeSearcher({})
    assert CareerSiteCollector([], searcher, ["career.ozon.ru"]).fetch(SINCE) == []
    assert CareerSiteCollector(["PM"], searcher, []).fetch(SINCE) == []
    assert searcher.queries == []  # без ролей/сайтов поиск не дёргаем


def test_fetch_isolates_search_failure_per_role() -> None:
    class FlakySearcher(Searcher):
        def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
            if "Manager" in query:
                raise RuntimeError("web-поиск упал")
            return [SearchResult(title="DS вакансия", url="https://career.ozon.ru/vacancy/3")]

    posts = CareerSiteCollector(
        ["Manager", "Data Scientist"], FlakySearcher(), ["career.ozon.ru"]
    ).fetch(SINCE)
    # упавшая роль пропущена, вторая собрана
    assert [p.url for p in posts] == ["https://career.ozon.ru/vacancy/3"]


def test_roles_capped_and_deduped() -> None:
    searcher = FakeSearcher({})
    coll = CareerSiteCollector(
        ["PM", "pm", "  PM  ", *[f"role{i}" for i in range(20)]],
        searcher,
        ["career.ozon.ru"],
        max_roles=3,
    )
    coll.fetch(SINCE)
    assert len(searcher.queries) == 3  # дубли свернуты, потолок 3
