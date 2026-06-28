"""Тесты дедупа (стадия 3) — SQLite seen-store, без сети."""

from __future__ import annotations

from pathlib import Path

from job_agent.dedup import SeenStore, content_key
from job_agent.models import Vacancy


def _vac(title: str, company: str | None = "Acme", url: str | None = None) -> Vacancy:
    return Vacancy(title=title, company=company, url=url, source="@chan")


def test_first_seen_then_marked() -> None:
    with SeenStore(":memory:") as store:
        v = _vac("Python-разработчик")
        assert store.is_seen(v) is False
        store.mark_seen(v)
        assert store.is_seen(v) is True


def test_mark_seen_idempotent() -> None:
    with SeenStore(":memory:") as store:
        v = _vac("Backend Engineer")
        store.mark_seen(v)
        store.mark_seen(v)  # повторно — не падает, не дублирует
        assert store.is_seen(v) is True


def test_content_key_ignores_case_and_whitespace() -> None:
    assert content_key(_vac("Python  Dev", "Acme")) == content_key(
        _vac("python dev", "acme")
    )
    assert content_key(_vac("A", "X")) != content_key(_vac("B", "X"))


def test_cross_source_dedup_by_title_company() -> None:
    # одна вакансия из двух каналов: разный url, тот же title+company
    with SeenStore(":memory:") as store:
        store.mark_seen(_vac("ML Engineer", "Acme", url="https://t.me/a/1"))
        dup = _vac("ml engineer", "ACME", url="https://t.me/b/2")
        assert store.is_seen(dup) is True


def test_dedup_by_url_when_company_differs() -> None:
    with SeenStore(":memory:") as store:
        store.mark_seen(_vac("Role", "Acme", url="https://x/1"))
        same_url = _vac("Другая", "Beta", url="https://x/1")
        assert store.is_seen(same_url) is True


def test_filter_new_in_batch_and_across_runs() -> None:
    batch = [
        _vac("A", "X", url="u1"),
        _vac("a", "x", url="u9"),  # дубль A по контенту
        _vac("B", "Y", url="u2"),
        _vac("C", "Z", url="u1"),  # дубль по url
    ]
    with SeenStore(":memory:") as store:
        fresh = store.filter_new(batch)
        assert [v.title for v in fresh] == ["A", "B"]
        # повторный прогон тех же данных → ноль новых
        assert store.filter_new(batch) == []


def test_persisted_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "seen.db"
    with SeenStore(db) as store:
        store.mark_seen(_vac("Persisted"))
    assert db.exists()
    with SeenStore(db) as store2:
        assert store2.is_seen(_vac("Persisted")) is True
        assert store2.filter_new([_vac("Persisted"), _vac("New")]) == [
            v for v in [_vac("New")]
        ]


def test_env_db_path(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "env.db"
    monkeypatch.setenv("JOB_AGENT_SEEN_DB", str(db))
    with SeenStore() as store:
        assert store.path == str(db)
        store.mark_seen(_vac("Env"))
    assert db.exists()


def test_no_url_dedup_only_by_content() -> None:
    with SeenStore(":memory:") as store:
        store.mark_seen(_vac("NoUrl", "Acme", url=None))
        assert store.is_seen(_vac("nourl", "acme", url=None)) is True
        assert store.is_seen(_vac("Different", "Acme", url=None)) is False
