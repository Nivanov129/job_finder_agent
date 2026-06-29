"""Юнит-тесты грубого фильтра по названию должности — фейк-движок, без сети."""

from __future__ import annotations

from datetime import UTC, datetime

from job_agent.models import RawPost
from job_agent.titlefilter import (
    derive_titles,
    filter_posts_by_titles,
    parse_titles,
)


class _FakeEngine:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    def complete(self, prompt: str, *, web_search: bool = False) -> str:
        self.calls += 1
        return self.answer


def _post(text: str) -> RawPost:
    return RawPost(raw_text=text, source="tg:x", url="u", date=datetime(2026, 1, 1, tzinfo=UTC))


def test_parse_titles_plain_and_fenced() -> None:
    assert parse_titles('["Product Manager", "Head of AI"]') == ["Product Manager", "Head of AI"]
    assert parse_titles('текст ```json\n["Продакт-менеджер"]\n```') == ["Продакт-менеджер"]


def test_parse_titles_drops_short_and_garbage() -> None:
    # слишком короткие (≤3) убираем — иначе ложные совпадения подстрокой
    assert parse_titles('["PM", "QA", "Product Manager"]') == ["Product Manager"]
    assert parse_titles("не массив") == []


def test_derive_titles_uses_engine() -> None:
    eng = _FakeEngine('["Product Manager", "Продакт-менеджер"]')
    titles = derive_titles(eng, "Резюме: продакт с метриками")
    assert titles == ["Product Manager", "Продакт-менеджер"]
    assert eng.calls == 1


def test_derive_titles_empty_resume_no_call() -> None:
    eng = _FakeEngine("[]")
    assert derive_titles(eng, "   ") == []
    assert eng.calls == 0


def test_filter_keeps_matching_case_insensitive() -> None:
    posts = [
        _post("Ищем Product Manager в финтех"),
        _post("Вакансия: Дизайнер интерфейсов"),
        _post("PRODUCT manager, удалёнка"),
    ]
    kept = filter_posts_by_titles(posts, ["Product Manager"])
    assert [p.raw_text for p in kept] == [
        "Ищем Product Manager в финтех",
        "PRODUCT manager, удалёнка",
    ]


def test_filter_empty_titles_keeps_all() -> None:
    posts = [_post("a"), _post("b")]
    assert filter_posts_by_titles(posts, []) == posts


def test_filter_lenient_word_match_keeps_phrasings() -> None:
    """Грубый фильтр щадящий: ловит дефис/пробел, порядок слов, предлоги, окончания."""
    from job_agent.models import RawPost
    from job_agent.titlefilter import filter_posts_by_titles

    titles = ["Product Manager", "Продакт-менеджер", "Менеджер продукта"]
    keep = [
        "Продакт менеджер в финтех",   # пробел вместо дефиса
        "Продуктовый менеджер",        # другое словообразование
        "Менеджер по продукту",        # предлог между словами
        "Senior Product Manager",      # с грейдом
    ]
    drop = ["Бэкенд-разработчик Python", "Дизайнер интерфейсов"]
    posts = [RawPost(raw_text=s, source="x") for s in keep + drop]
    kept = {p.raw_text for p in filter_posts_by_titles(posts, titles)}
    assert set(keep) <= kept, keep
    assert not (set(drop) & kept), drop
