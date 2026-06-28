"""Коллектор приватных Telegram-каналов через Telethon (опционально).

Активен только при заполненных `telethon_creds` (api_id/api_hash/session). Весь
сетевой код (реальный Telethon-клиент) спрятан за фасадом `MessageFetcher`,
который в тестах подменяется фейком — юнит-тесты в сеть не ходят и не требуют
установленного telethon. Чистая функция `build_posts` собирает `RawPost` из
сообщений и фильтрует по дате; её и тестируем.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..config import TelethonCreds
from ..models import RawPost
from .base import Collector

__all__ = [
    "TelegramPrivateCollector",
    "PrivateMessage",
    "MessageFetcher",
    "build_posts",
    "make_private_collector",
    "creds_present",
]


@dataclass
class PrivateMessage:
    """Сообщение приватного канала в нейтральной форме (без типов telethon)."""

    text: str
    message_id: int
    date: datetime | None = None


# (handle, since) -> сообщения канала. Дефолт ходит в сеть через telethon;
# в тестах подменяется фейком.
MessageFetcher = Callable[[str, datetime], list[PrivateMessage]]

_logger = logging.getLogger("job_agent.collectors.telegram_private")


def _as_aware(dt: datetime) -> datetime:
    """Привести datetime к tz-aware (наивный считаем UTC) для сравнения."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def creds_present(creds: TelethonCreds | None) -> bool:
    """Достаточно ли creds, чтобы поднять реальный Telethon-клиент."""
    return bool(creds and creds.api_id and creds.api_hash and creds.session)


def creds_from_env() -> TelethonCreds | None:
    """Собрать creds из окружения (TELEGRAM_API_ID/HASH/SESSION) — секреты в .env.

    Так строка сессии (секрет) не попадает в config.json. Возвращает None, если
    чего-то не хватает.
    """
    import os

    creds = TelethonCreds(
        api_id=os.environ.get("TELEGRAM_API_ID"),
        api_hash=os.environ.get("TELEGRAM_API_HASH"),
        session=os.environ.get("TELEGRAM_SESSION"),
    )
    return creds if creds_present(creds) else None


def build_posts(
    messages: Iterable[PrivateMessage],
    handle: str,
    since: datetime,
) -> list[RawPost]:
    """Собрать `RawPost` из сообщений канала, отбросив пустые и старше `since`.

    Ссылка достраивается как `https://t.me/<handle>/<id>`, источник — `tg:<handle>`.
    """
    since_aware = _as_aware(since)
    out: list[RawPost] = []
    for msg in messages:
        text = msg.text.strip()
        if not text:
            continue
        if msg.date is not None and _as_aware(msg.date) < since_aware:
            continue
        out.append(
            RawPost(
                raw_text=text,
                source=f"tg:{handle}",
                url=f"https://t.me/{handle}/{msg.message_id}",
                date=msg.date,
            )
        )
    return out


def _telethon_fetcher(creds: TelethonCreds) -> MessageFetcher:  # pragma: no cover - реальная сеть
    """Построить фетчер на реальном Telethon-клиенте (вне юнит-тестов)."""

    def _fetch(handle: str, since: datetime) -> list[PrivateMessage]:
        import asyncio

        from telethon import TelegramClient
        from telethon.sessions import StringSession

        since_aware = _as_aware(since)

        async def _run() -> list[PrivateMessage]:
            client = TelegramClient(
                StringSession(creds.session),
                int(creds.api_id),  # type: ignore[arg-type]
                creds.api_hash,
            )
            await client.start()
            msgs: list[PrivateMessage] = []
            try:
                async for msg in client.iter_messages(handle):
                    if msg.date is not None and _as_aware(msg.date) < since_aware:
                        break  # iter_messages идёт от новых к старым
                    text = msg.message or ""
                    if text.strip():
                        msgs.append(
                            PrivateMessage(text=text, message_id=msg.id, date=msg.date)
                        )
            finally:
                await client.disconnect()
            return msgs

        return asyncio.run(_run())

    return _fetch


class TelegramPrivateCollector(Collector):
    """Сбор постов из приватных каналов через Telethon.

    `fetcher` инъектируется в тестах. В проде он строится лениво из `creds` при
    первом `fetch`; без валидных creds и без инъекции — внятная ошибка.
    """

    def __init__(
        self,
        handles: Iterable[str],
        creds: TelethonCreds | None = None,
        fetcher: MessageFetcher | None = None,
    ) -> None:
        self._handles = [h.lstrip("@").strip() for h in handles if h.strip()]
        self._creds = creds
        self._fetcher = fetcher

    def _resolve_fetcher(self) -> MessageFetcher:
        if self._fetcher is None:
            if not creds_present(self._creds):
                raise RuntimeError(
                    "TelegramPrivateCollector требует telethon_creds "
                    "(api_id/api_hash/session) или инъекции fetcher."
                )
            assert self._creds is not None
            self._fetcher = _telethon_fetcher(self._creds)
        return self._fetcher

    def fetch(self, since: datetime) -> list[RawPost]:
        fetcher = self._resolve_fetcher()
        out: list[RawPost] = []
        for handle in self._handles:
            # Изоляция по каналу: один нерезолвимый/приватный хэндл (напр. голый
            # numeric-id без username) не должен ронять сбор по остальным.
            try:
                out.extend(build_posts(fetcher(handle, since), handle, since))
            except Exception as exc:
                _logger.warning("канал %s пропущен: %s", handle, exc)
        return out


def make_private_collector(
    handles: Iterable[str],
    creds: TelethonCreds | None,
    fetcher: MessageFetcher | None = None,
) -> TelegramPrivateCollector | None:
    """Фабрика: вернуть коллектор, иначе `None` если приватный сбор неактивен.

    Активен только при валидных `creds` (или явной инъекции `fetcher` в тестах).
    Отсутствие creds — штатный случай (приватные каналы опциональны), не ошибка.
    """
    if fetcher is None and not creds_present(creds):
        return None
    return TelegramPrivateCollector(handles, creds=creds, fetcher=fetcher)
