"""Дедуп (стадия 3): SQLite seen-store виденных вакансий.

Ключ дедупа двойной: хэш нормализованного `title+company` И url. Вакансия
считается виденной, если совпал контент-ключ ИЛИ url — это ловит кросс-источник
(одна вакансия из разных каналов: разный url, но тот же `title+company`). API
идемпотентен: повторный `mark_seen` ничего не дублирует, повторный прогон даёт
ноль новых. Путь к БД — из аргумента, иначе env `JOB_AGENT_SEEN_DB`, иначе
дефолт `job_agent_seen.db` в текущем каталоге; `:memory:` — для тестов.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path
from types import TracebackType

from .models import Vacancy

__all__ = ["SeenStore", "content_key", "DEFAULT_DB_PATH", "ENV_DB_PATH"]

ENV_DB_PATH = "JOB_AGENT_SEEN_DB"
DEFAULT_DB_PATH = "job_agent_seen.db"

_WS = re.compile(r"\s+")


def _norm(value: str | None) -> str:
    """Привести строку к каноничному виду: нижний регистр, схлопнутые пробелы."""
    return _WS.sub(" ", (value or "").strip().lower())


def content_key(vacancy: Vacancy) -> str:
    """Стабильный хэш по нормализованному `title+company` (кросс-источник)."""
    payload = f"{_norm(vacancy.title)}\x00{_norm(vacancy.company)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_db_path(db_path: str | Path | None) -> str:
    if db_path is not None:
        return str(db_path)
    return os.environ.get(ENV_DB_PATH) or DEFAULT_DB_PATH


class SeenStore:
    """Хранилище виденных вакансий поверх SQLite.

    Контент-ключи и url лежат отдельно — вакансия виденная, если совпало любое.
    Использовать как контекст-менеджер либо явно звать `close()`.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.path = _resolve_db_path(db_path)
        if self.path not in (":memory:", "") and not self.path.startswith("file:"):
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS seen_content (
                key TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS seen_url (
                url TEXT PRIMARY KEY
            );
            """
        )
        self._conn.commit()

    def is_seen(self, vacancy: Vacancy) -> bool:
        """True, если контент-ключ ИЛИ url вакансии уже встречались."""
        cur = self._conn.execute(
            "SELECT 1 FROM seen_content WHERE key = ? LIMIT 1",
            (content_key(vacancy),),
        )
        if cur.fetchone() is not None:
            return True
        url = _norm_url(vacancy.url)
        if url is None:
            return False
        cur = self._conn.execute(
            "SELECT 1 FROM seen_url WHERE url = ? LIMIT 1", (url,)
        )
        return cur.fetchone() is not None

    def mark_seen(self, vacancy: Vacancy) -> None:
        """Запомнить вакансию (идемпотентно). Пишет контент-ключ и url."""
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_content (key) VALUES (?)",
            (content_key(vacancy),),
        )
        url = _norm_url(vacancy.url)
        if url is not None:
            self._conn.execute(
                "INSERT OR IGNORE INTO seen_url (url) VALUES (?)", (url,)
            )
        self._conn.commit()

    def filter_new(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        """Вернуть только невиденные вакансии и сразу пометить их виденными.

        Внутрипрогонный дедуп тоже: два дубля в одной пачке → останется один.
        """
        out: list[Vacancy] = []
        for vacancy in vacancies:
            if self.is_seen(vacancy):
                continue
            self.mark_seen(vacancy)
            out.append(vacancy)
        return out

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SeenStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _norm_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    return url or None
