"""Локальная БД подборки (SQLite): накопление найденных вакансий между прогонами.

Прогон апсёртит финалистов сюда, а подборка читается из БД — так она РАСТЁТ, а не
перетирается каждым прогоном (важно для агент-режима: он находит только новое с
прошлого раза). Дедуп по ключу `title+company` (как `SeenStore`), статус
`active|archived` — «скрыть/в архив». Повторная находка не воскрешает архивную и
не плодит дублей (идемпотентный upsert: обновляет данные и `last_seen`).

Путь к БД — из аргумента, иначе env `JOB_AGENT_MATCH_DB`, иначе `matches.db`;
`:memory:` — для тестов. Только stdlib `sqlite3`, без ORM/зависимостей. Соединение
НЕ потокобезопасно — открывай `MatchStore` на операцию (WAL даёт конкурентные
чтение/запись разными соединениями к одному файлу).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["MatchStore", "match_key", "ENV_DB_PATH", "DEFAULT_DB_PATH"]

ENV_DB_PATH = "JOB_AGENT_MATCH_DB"
DEFAULT_DB_PATH = "matches.db"
_WS = re.compile(r"\s+")


def _norm(value: str | None) -> str:
    return _WS.sub(" ", (value or "").strip().lower())


def match_key(role: str | None, company: str | None, link: str | None = "") -> str:
    """Стабильный ключ вакансии: хэш `role+company` (кросс-источник), иначе ссылка."""
    payload = (
        f"{_norm(role)}\x00{_norm(company)}"
        if (role or company)
        else _norm(link)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_db_path(db_path: str | Path | None) -> str:
    if db_path is not None:
        return str(db_path)
    return os.environ.get(ENV_DB_PATH) or DEFAULT_DB_PATH


class MatchStore:
    """Накопительное хранилище подборки поверх SQLite (контекст-менеджер)."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.path = _resolve_db_path(db_path)
        if self.path not in (":memory:", "") and not self.path.startswith("file:"):
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # Скоринг апсёртит из ПАРАЛЛЕЛЬНЫХ потоков (config.parallelism), а sqlite по
        # умолчанию привязан к создавшему потоку. check_same_thread=False + общий
        # лок на операции делают одно соединение безопасным для всех потоков.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=4000")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS matches (
                key TEXT PRIMARY KEY,
                role TEXT, company TEXT, track TEXT,
                resume INTEGER, map INTEGER, verdict TEXT, link TEXT,
                data TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def upsert(self, match: dict[str, Any], *, now: datetime | None = None) -> str:
        """Добавить/обновить вакансию по ключу; вернуть ключ.

        Идемпотентно: повторная находка обновляет данные и `last_seen`, но НЕ
        трогает `status` (архивная остаётся архивной) и `first_seen`.
        """
        stamp = (now or datetime.now(UTC)).isoformat()
        key = match.get("key") or match_key(
            match.get("role"), match.get("company"), match.get("link")
        )
        data = json.dumps({**match, "key": key}, ensure_ascii=False)
        cols = (
            match.get("role"), match.get("company"), match.get("track"),
            int(match.get("resume") or 0), int(match.get("map") or 0),
            match.get("verdict"), match.get("link"), data,
        )
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM matches WHERE key=?", (key,)
            ).fetchone()
            if exists:
                self._conn.execute(
                    "UPDATE matches SET role=?,company=?,track=?,resume=?,map=?,"
                    "verdict=?,link=?,data=?,last_seen=? WHERE key=?",
                    (*cols, stamp, key),
                )
            else:
                self._conn.execute(
                    "INSERT INTO matches(key,role,company,track,resume,map,verdict,"
                    "link,data,status,first_seen,last_seen) "
                    "VALUES(?,?,?,?,?,?,?,?,?,'active',?,?)",
                    (key, *cols, stamp, stamp),
                )
            self._conn.commit()
        return key

    def list(
        self,
        *,
        status: str = "active",
        track: str | None = None,
        min_resume: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Вакансии по статусу (новые первыми); фильтры по треку и мин. % резюме."""
        query = "SELECT data, first_seen, last_seen, status FROM matches WHERE status=?"
        args: list[Any] = [status]
        if track:
            query += " AND track=?"
            args.append(track)
        if min_resume is not None:
            query += " AND resume>=?"
            args.append(int(min_resume))
        query += " ORDER BY first_seen DESC, resume DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = json.loads(row["data"])
            item["first_seen"] = row["first_seen"]
            item["last_seen"] = row["last_seen"]
            item["status"] = row["status"]
            out.append(item)
        return out

    def set_status(self, key: str, status: str) -> bool:
        """Сменить статус (напр. 'archived'); True — если строка нашлась."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE matches SET status=? WHERE key=?", (status, key)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> MatchStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
