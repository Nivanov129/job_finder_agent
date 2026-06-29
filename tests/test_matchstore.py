"""Тесты локальной БД подборки (job_agent/matchstore.py) — sqlite, без сети."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from job_agent.matchstore import MatchStore, match_key


def _m(role: str, company: str, **over: object) -> dict[str, object]:
    return {"role": role, "company": company, "resume": 80, "map": 40, "link": "u", **over}


def test_match_key_stable_by_role_company() -> None:
    assert match_key("Product Manager", "Acme") == match_key("  product   manager ", "ACME")
    assert match_key("PM", "A") != match_key("PM", "B")


def test_upsert_and_list_active() -> None:
    with MatchStore(":memory:") as s:
        s.upsert(_m("PM", "Acme", resume=88))
        s.upsert(_m("DS", "Beta", resume=70))
        rows = s.list()
        assert [r["role"] for r in rows] == ["DS", "PM"]  # новые первыми (first_seen DESC)
        assert all("key" in r and "first_seen" in r for r in rows)


def test_upsert_idempotent_no_duplicates() -> None:
    with MatchStore(":memory:") as s:
        s.upsert(_m("PM", "Acme"))
        s.upsert(_m("PM", "Acme", resume=95))  # та же вакансия — обновление
        rows = s.list()
        assert len(rows) == 1
        assert rows[0]["resume"] == 95  # данные обновились


def test_first_seen_preserved_on_reupsert() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 2, 1, tzinfo=UTC)
    with MatchStore(":memory:") as s:
        s.upsert(_m("PM", "Acme"), now=t0)
        s.upsert(_m("PM", "Acme"), now=t1)
        row = s.list()[0]
        assert row["first_seen"] == t0.isoformat()
        assert row["last_seen"] == t1.isoformat()


def test_archive_hides_from_active_and_survives_reupsert() -> None:
    with MatchStore(":memory:") as s:
        key = s.upsert(_m("PM", "Acme"))
        assert s.set_status(key, "archived") is True
        assert s.list() == []  # из активных ушла
        assert len(s.list(status="archived")) == 1
        # повторная находка НЕ воскрешает архивную
        s.upsert(_m("PM", "Acme", resume=99))
        assert s.list() == []
        assert s.list(status="archived")[0]["resume"] == 99


def test_filters_track_and_min_resume() -> None:
    with MatchStore(":memory:") as s:
        s.upsert(_m("PM", "Acme", track="A", resume=90))
        s.upsert(_m("DS", "Beta", track="B", resume=50))
        assert [r["role"] for r in s.list(track="A")] == ["PM"]
        assert [r["role"] for r in s.list(min_resume=80)] == ["PM"]


def test_set_status_unknown_key_false() -> None:
    with MatchStore(":memory:") as s:
        assert s.set_status("nope", "archived") is False


def test_persists_across_connections(tmp_path: Path) -> None:
    db = tmp_path / "matches.db"
    with MatchStore(db) as s:
        s.upsert(_m("PM", "Acme"))
    with MatchStore(db) as s:  # новое соединение видит запись
        assert [r["role"] for r in s.list()] == ["PM"]


def test_upsert_from_other_thread(tmp_path: Path) -> None:
    """Регресс: скоринг апсёртит из параллельных потоков — sqlite не должен падать
    с «objects created in a thread can only be used in that same thread»."""
    import threading

    store = MatchStore(tmp_path / "matches.db")
    errors: list[Exception] = []

    def work(i: int) -> None:
        try:
            store.upsert(_m(f"Role{i}", f"Co{i}"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(store.list()) == 10  # все 10 из разных потоков сохранились
    store.close()
