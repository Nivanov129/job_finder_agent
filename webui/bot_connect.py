"""Подключение Telegram-бота для уведомлений: захват chat_id и тест-сообщение.

Бота создаёт сам пользователь у @BotFather; токен — секрет, живёт в `.env`
(`TELEGRAM_BOT_TOKEN`). Чтобы узнать, КУДА слать (личный чат владельца),
пользователь пишет боту `/start`, а мы читаем `getUpdates` и берём `chat.id`
последнего личного сообщения. Реальный HTTP — за инъекцией (`http_get`/
`http_post`); чистый разбор `parse_chat_id_from_updates` тестируется без сети.

Инвариант приватности: бот пишет ТОЛЬКО владельцу (его личный chat), без авто-DM
кому-либо ещё — поэтому берём именно `type == "private"`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = [
    "parse_chat_id_from_updates",
    "resolve_owner_chat_id",
    "send_test_message",
    "BOT_TOKEN_ENV",
]

#: Имя переменной окружения с токеном бота (секрет, живёт в `.env`).
BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
_API = "https://api.telegram.org"

HttpGet = Callable[[str], dict[str, Any]]
HttpPost = Callable[[str, dict[str, Any]], dict[str, Any]]


def parse_chat_id_from_updates(data: dict[str, Any]) -> int | None:
    """`chat.id` последнего ЛИЧНОГО сообщения из ответа getUpdates (или None).

    Берём самый свежий приватный чат — это владелец, написавший боту `/start`.
    Группы/каналы игнорируем (уведомления только в личку).
    """
    if not isinstance(data, dict) or not data.get("ok"):
        return None
    chat_id: int | None = None
    for upd in data.get("result") or []:
        if not isinstance(upd, dict):
            continue
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") == "private" and isinstance(chat.get("id"), int):
            chat_id = chat["id"]  # последний выигрывает — самый свежий
    return chat_id


def resolve_owner_chat_id(token: str, *, http_get: HttpGet | None = None) -> int | None:
    """Спросить getUpdates и вернуть chat_id владельца (или None, если не писал)."""
    get = http_get or _httpx_get
    try:
        data = get(f"{_API}/bot{token}/getUpdates")
    except Exception:  # сеть/неверный токен — мягко None
        return None
    return parse_chat_id_from_updates(data)


def send_test_message(
    token: str, chat_id: int | str, text: str, *, http_post: HttpPost | None = None
) -> bool:
    """Отправить тест-сообщение в личный чат владельца. True — если Bot API принял."""
    post = http_post or _httpx_post
    try:
        res = post(
            f"{_API}/bot{token}/sendMessage", {"chat_id": chat_id, "text": text}
        )
    except Exception:
        return False
    return bool(res.get("ok")) if isinstance(res, dict) else False


def _httpx_get(url: str) -> dict[str, Any]:  # pragma: no cover - реальная сеть
    import httpx

    response = httpx.get(url, timeout=20.0)
    response.raise_for_status()
    return response.json()


def _httpx_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
    import httpx

    response = httpx.post(url, json=payload, timeout=20.0)
    response.raise_for_status()
    return response.json()
