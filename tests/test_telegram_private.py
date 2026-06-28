"""Тесты приватного TG-коллектора на фейке клиента (без сети, без telethon)."""

from __future__ import annotations

from datetime import UTC, datetime

from job_agent.collectors.telegram_private import (
    PrivateMessage,
    TelegramPrivateCollector,
    build_posts,
    creds_present,
    make_private_collector,
)
from job_agent.config import TelethonCreds

_MESSAGES = {
    "alphajobs": [
        PrivateMessage(
            "Python-разработчик в AlphaCo", 100, datetime(2024, 6, 1, 9, 30, tzinfo=UTC)
        ),
        PrivateMessage("Senior Backend @ BetaLabs", 101, datetime(2024, 6, 20, tzinfo=UTC)),
        PrivateMessage("   ", 102, datetime(2024, 6, 25, tzinfo=UTC)),  # пустой → отброшен
    ],
    "betajobs": [
        PrivateMessage("DevOps @ GammaSoft", 200, datetime(2024, 6, 22, tzinfo=UTC)),
    ],
}


def _fake_fetcher(handle: str, _since: datetime) -> list[PrivateMessage]:
    return list(_MESSAGES.get(handle, []))


def test_build_posts_skips_empty_and_old_and_builds_url() -> None:
    since = datetime(2024, 6, 15, tzinfo=UTC)
    posts = build_posts(_MESSAGES["alphajobs"], "alphajobs", since)

    # пост 100 (1 июня) отсечён по дате, 102 — пустой; остаётся только 101
    assert len(posts) == 1
    post = posts[0]
    assert post.source == "tg:alphajobs"
    assert post.url == "https://t.me/alphajobs/101"
    assert post.raw_text == "Senior Backend @ BetaLabs"


def test_fetch_aggregates_handles_and_strips_prefix() -> None:
    collector = TelegramPrivateCollector(
        ["@alphajobs", "betajobs"], fetcher=_fake_fetcher
    )
    posts = collector.fetch(datetime(2024, 1, 1, tzinfo=UTC))

    assert {p.url for p in posts} == {
        "https://t.me/alphajobs/100",
        "https://t.me/alphajobs/101",
        "https://t.me/betajobs/200",
    }


def test_fetch_filters_by_since() -> None:
    collector = TelegramPrivateCollector(["alphajobs"], fetcher=_fake_fetcher)
    posts = collector.fetch(datetime(2024, 6, 15, tzinfo=UTC))
    assert {p.url for p in posts} == {"https://t.me/alphajobs/101"}


def test_naive_since_treated_as_utc() -> None:
    collector = TelegramPrivateCollector(["alphajobs"], fetcher=_fake_fetcher)
    posts = collector.fetch(datetime(2024, 1, 1))  # наивная дата
    assert len(posts) == 2  # пустой пост отброшен


def test_creds_present_requires_all_fields() -> None:
    assert creds_present(TelethonCreds(api_id="1", api_hash="h", session="s"))
    assert not creds_present(None)
    assert not creds_present(TelethonCreds(api_id="1", api_hash="h"))
    assert not creds_present(TelethonCreds())


def test_factory_returns_none_without_creds() -> None:
    # приватные каналы опциональны: нет creds → коллектора нет (не ошибка)
    assert make_private_collector(["alphajobs"], None) is None
    assert make_private_collector(["alphajobs"], TelethonCreds(api_id="1")) is None

    # с валидными creds — коллектор есть
    creds = TelethonCreds(api_id="1", api_hash="h", session="s")
    assert isinstance(make_private_collector(["alphajobs"], creds), TelegramPrivateCollector)

    # инъекция fetcher активирует коллектор и без creds (для тестов)
    injected = make_private_collector(["alphajobs"], None, fetcher=_fake_fetcher)
    assert isinstance(injected, TelegramPrivateCollector)


def test_fetch_without_creds_or_fetcher_raises() -> None:
    collector = TelegramPrivateCollector(["alphajobs"], creds=None)
    try:
        collector.fetch(datetime(2024, 1, 1, tzinfo=UTC))
    except RuntimeError as exc:
        assert "telethon_creds" in str(exc)
    else:
        raise AssertionError("ожидалась RuntimeError без creds/fetcher")
