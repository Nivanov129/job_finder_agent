"""Тесты публичного TG-коллектора на сохранённом HTML-фикстуре (без сети)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from job_agent.collectors.telegram_public import (
    TelegramPublicCollector,
    parse_tme_html,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tme_channel.html"


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _fake_fetcher(_url: str) -> str:
    return _html()


def test_parse_extracts_text_url_date_and_skips_media_only() -> None:
    posts = parse_tme_html(_html(), "testjobs")

    # пост 103 — медиа без текста → отброшен
    assert len(posts) == 3

    first = posts[0]
    assert first.source == "tg:testjobs"
    assert first.url == "https://t.me/testjobs/100"
    assert first.date == datetime(2024, 6, 1, 9, 30, tzinfo=UTC)
    assert "Python-разработчик" in first.raw_text
    assert "\n" in first.raw_text  # <br> → перевод строки

    # текст из вложенных тегов и ссылок сохраняется
    second = posts[1]
    assert "Senior Backend" in second.raw_text
    assert "BetaLabs" in second.raw_text


def test_fetch_filters_by_since() -> None:
    collector = TelegramPublicCollector(["testjobs"], fetcher=_fake_fetcher)

    since = datetime(2024, 6, 15, tzinfo=UTC)
    posts = collector.fetch(since)

    # отсекается пост от 1 июня; остаются 20 и 25 июня
    assert {p.url for p in posts} == {
        "https://t.me/testjobs/101",
        "https://t.me/testjobs/102",
    }


def test_fetch_handles_naive_since_and_handle_prefix() -> None:
    collector = TelegramPublicCollector(["@testjobs"], fetcher=_fake_fetcher)

    # наивная дата трактуется как UTC, сравнение не падает
    posts = collector.fetch(datetime(2024, 1, 1))
    assert len(posts) == 3
    assert all(p.source == "tg:testjobs" for p in posts)


def test_multiple_handles_aggregated() -> None:
    collector = TelegramPublicCollector(["a", "b"], fetcher=_fake_fetcher)
    posts = collector.fetch(datetime(2024, 1, 1, tzinfo=UTC))
    # по 3 поста с каждого канала
    assert len(posts) == 6
