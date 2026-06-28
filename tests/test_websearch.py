"""Тесты web-поиска (searxng / serp) на фейках транспорта.

Ни один тест не выходит в сеть: вместо реального httpx инъектируется фейк-GET.
"""

from __future__ import annotations

from typing import Any

import pytest

from job_agent.config import Config, ConfigError, Track, WebSearch
from job_agent.websearch import (
    FakeSearcher,
    Searcher,
    SearchResult,
    make_searcher,
)
from job_agent.websearch.searxng import SearxngSearcher
from job_agent.websearch.searxng import build_request as searxng_build_request
from job_agent.websearch.searxng import parse_response as searxng_parse_response
from job_agent.websearch.serp import DEFAULT_BASE_URL, SerpSearcher
from job_agent.websearch.serp import build_request as serp_build_request
from job_agent.websearch.serp import parse_response as serp_parse_response


def _config(web_search: WebSearch | None, **kw: object) -> Config:
    return Config(
        version=1,
        tracks=[Track(id="t1", name="Трек", resume_path="./r.pdf")],
        scoring_engine="cli",
        output_mode="xlsx",
        web_search=web_search,
        **kw,  # type: ignore[arg-type]
    )


# --- SearXNG -----------------------------------------------------------------


def test_searxng_build_request() -> None:
    url, params = searxng_build_request("https://searx.local/", "acme компания")
    assert url == "https://searx.local/search"
    assert params == {"q": "acme компания", "format": "json"}


def test_searxng_parse_response_maps_fields_and_limits() -> None:
    data: dict[str, Any] = {
        "results": [
            {"title": "A", "url": "https://a", "content": "сниппет a"},
            {"title": "B", "url": "https://b", "content": "сниппет b"},
            {"title": "C", "url": "https://c", "content": "сниппет c"},
        ]
    }
    out = searxng_parse_response(data, max_results=2)
    assert len(out) == 2
    assert out[0] == SearchResult(title="A", url="https://a", snippet="сниппет a")


def test_searxng_parse_response_tolerates_junk() -> None:
    data: dict[str, Any] = {"results": ["bad", {}, {"url": "https://x"}]}
    out = searxng_parse_response(data, max_results=5)
    assert [r.url for r in out] == ["https://x"]


def test_searxng_parse_response_no_results_key() -> None:
    assert searxng_parse_response({}, max_results=5) == []


def test_searxng_searcher_through_injected_transport() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def fake_get(url: str, params: dict[str, str]) -> dict[str, Any]:
        seen.append((url, params))
        return {"results": [{"title": "T", "url": "https://t", "content": "c"}]}

    s = SearxngSearcher("https://searx.local", transport=fake_get)
    out = s.search("вопрос", max_results=3)
    assert out == [SearchResult(title="T", url="https://t", snippet="c")]
    assert seen == [("https://searx.local/search", {"q": "вопрос", "format": "json"})]


def test_searxng_empty_url_raises() -> None:
    with pytest.raises(ConfigError):
        SearxngSearcher("")


# --- SERP --------------------------------------------------------------------


def test_serp_build_request_includes_key_and_engine() -> None:
    url, params = serp_build_request(DEFAULT_BASE_URL, "SECRET", "acme")
    assert url == "https://serpapi.com/search"
    assert params == {"q": "acme", "engine": "google", "api_key": "SECRET"}


def test_serp_parse_response_maps_fields() -> None:
    data: dict[str, Any] = {
        "organic_results": [
            {"title": "A", "link": "https://a", "snippet": "s a"},
            {"title": "B", "link": "https://b"},
        ]
    }
    out = serp_parse_response(data, max_results=5)
    assert out[0] == SearchResult(title="A", url="https://a", snippet="s a")
    assert out[1] == SearchResult(title="B", url="https://b", snippet="")


def test_serp_parse_response_tolerates_junk() -> None:
    assert serp_parse_response({"organic_results": [1, {}]}, max_results=5) == []
    assert serp_parse_response({}, max_results=5) == []


def test_serp_searcher_through_injected_transport() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def fake_get(url: str, params: dict[str, str]) -> dict[str, Any]:
        seen.append((url, params))
        return {"organic_results": [{"title": "T", "link": "https://t", "snippet": "c"}]}

    s = SerpSearcher("KEY", transport=fake_get)
    out = s.search("вопрос", max_results=1)
    assert out == [SearchResult(title="T", url="https://t", snippet="c")]
    assert seen[0][1]["api_key"] == "KEY"


def test_serp_empty_key_raises() -> None:
    with pytest.raises(ConfigError):
        SerpSearcher("")


def test_serp_secret_not_in_repr() -> None:
    s = SerpSearcher("SUPERSECRET")
    assert "SUPERSECRET" not in repr(s)


# --- Фабрика -----------------------------------------------------------------


def test_make_searcher_override_wins() -> None:
    fake = FakeSearcher()
    cfg = _config(None)
    assert make_searcher(cfg, override=fake) is fake


def test_make_searcher_searxng() -> None:
    cfg = _config(WebSearch(provider="searxng", url="https://searx.local"))
    assert isinstance(make_searcher(cfg), SearxngSearcher)


def test_make_searcher_serp() -> None:
    cfg = _config(WebSearch(provider="serp", api_key="KEY"))
    assert isinstance(make_searcher(cfg), SerpSearcher)


def test_make_searcher_no_section_defaults_searxng() -> None:
    # Секция web_search необязательна — по умолчанию searxng на дефолтном адресе.
    assert isinstance(make_searcher(_config(None)), SearxngSearcher)


def test_make_searcher_unknown_provider_raises() -> None:
    cfg = _config(WebSearch(provider="searxng"))
    cfg.web_search.provider = "bogus"  # type: ignore[union-attr]
    with pytest.raises(ConfigError):
        make_searcher(cfg)


def test_make_searcher_searxng_missing_url_uses_default(monkeypatch) -> None:
    # Без url — дефолтный адрес SearXNG (env переопределяет), не ошибка.
    monkeypatch.delenv("JOB_AGENT_SEARXNG_URL", raising=False)
    searcher = make_searcher(_config(WebSearch(provider="searxng")))
    assert isinstance(searcher, SearxngSearcher)


def test_make_searcher_serp_missing_key_raises() -> None:
    with pytest.raises(ConfigError):
        make_searcher(_config(WebSearch(provider="serp")))


# --- Фейк --------------------------------------------------------------------


def test_fake_searcher_records_and_limits() -> None:
    fake = FakeSearcher(
        [SearchResult(title="A", url="https://a"), SearchResult(title="B", url="https://b")]
    )
    out = fake.search("q", max_results=1)
    assert len(out) == 1
    assert fake.call_count == 1
    assert fake.last_query == "q"


def test_fake_searcher_callable() -> None:
    fake = FakeSearcher(lambda q: [SearchResult(title=q, url="https://x")])
    assert fake.search("hello")[0].title == "hello"


def test_fake_searcher_is_searcher() -> None:
    assert isinstance(FakeSearcher(), Searcher)
