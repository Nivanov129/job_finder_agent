"""Отправка новых вакансий агент-прогона в Telegram-бот владельца.

Вызывается после АГЕНТ-прогона: если задан токен бота (`.env`
`TELEGRAM_BOT_TOKEN`) и `config.owner_chat_id` — шлём дайджест финалистов в
личный чат владельца через существующий `send_digest`. Без токена/chat_id или
без результатов — тихий no-op. «Новизна» гарантируется выше по стеку: агент
собирает посты с момента прошлого прогона и дедупит персистентным `SeenStore`,
поэтому сюда приходят только новые вакансии.

Сеть — за `BotTransport` (в тестах фейк); эта функция тестируется без сети.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import TYPE_CHECKING

from job_agent.output.bot import BotTransport, TelegramBotTransport, send_digest

from .bot_connect import BOT_TOKEN_ENV

if TYPE_CHECKING:
    from job_agent.config import Config
    from job_agent.models import EnrichedResult

__all__ = ["notify_new_vacancies"]


def notify_new_vacancies(
    config: Config,
    results: Iterable[EnrichedResult],
    *,
    transport: BotTransport | None = None,
) -> int:
    """Отправить новые вакансии в бот владельца; вернуть число карточек (0 — no-op).

    No-op (возвращает 0), если нет токена бота, нет `owner_chat_id` или пусто.
    """
    token = os.environ.get(BOT_TOKEN_ENV, "").strip()
    chat_id = config.owner_chat_id
    results = list(results)
    if not token or not chat_id or not results:
        return 0
    bot = transport or TelegramBotTransport(token)
    cards = send_digest(
        results,
        bot,
        chat_id,
        is_single_track=config.is_single_track,
        cover_letter_threshold=config.cover_letter_threshold,
    )
    return len(cards)
