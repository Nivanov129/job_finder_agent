"""Интерактивный логин в Telegram (Telethon) для web-UI + выгрузка/классификация
каналов.

Логин: api_id/api_hash + телефон → код → (2FA-пароль) → строка сессии. Клиент
Telethon живёт между HTTP-запросами на выделенном asyncio-loop в фоновом потоке
(каждый запрос — отдельный HTTP, а клиент один). Реальный Telethon — за фабрикой
клиента (`client_factory`), в тестах фейк; сетевые части помечены no-cover.

`classify_channels` — чистая функция: спрашивает AI-движок, какие из каналов про
вакансии, и парсит строгий JSON. Секреты (api_hash, session) не логируются.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from job_agent.engines.base import Engine

from .env_store import merge_env

__all__ = [
    "TelegramLogin",
    "classify_channels",
    "build_classify_prompt",
    "parse_channel_ids",
    "qr_data_uri",
    "TELEGRAM_ENV_KEYS",
]


def qr_data_uri(url: str) -> str:
    """PNG data-URI с QR-кодом для строки `tg://login?token=…`.

    Рисуем локально (segno, чистый Python) — никакого CDN/сети, как требует
    инвариант проекта. Браузер вставляет результат прямо в `<img src=…>`.
    """
    import segno

    return segno.make(url, error="m").png_data_uri(scale=6, border=2)

# Ключи авторизации Telegram в `.env` (секреты, не в config.json и не в коде).
# api_id/api_hash у каждого свои (my.telegram.org) — НЕ зашиваем в публичный код.
TELEGRAM_ENV_KEYS = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION")


# ── AI-классификация каналов (чистая логика, тестируется на фейк-движке) ──────


def build_classify_prompt(channels: list[dict[str, Any]]) -> str:
    """Промт: из списка каналов выбрать те, что публикуют вакансии/работу."""
    lines = []
    for ch in channels:
        title = str(ch.get("title", "")).replace("\n", " ").strip()
        desc = str(ch.get("description", "") or "").replace("\n", " ").strip()[:200]
        lines.append(f'- id={ch.get("id")} | {title}' + (f" — {desc}" if desc else ""))
    listing = "\n".join(lines)
    return (
        "Ниже список Telegram-каналов пользователя (id, название, описание). "
        "Верни СТРОГО JSON-массив id тех каналов, что регулярно публикуют ВАКАНСИИ "
        "или предложения работы (джоб-борды, наймовые каналы, каналы компаний с "
        "вакансиями). Личные блоги, новости, мемы, обучение без вакансий — не "
        "включай. Только JSON-массив id, без пояснений.\n\n"
        f"Каналы:\n{listing}\n\n"
        'Формат ответа: [id1, id2, ...] (массив строк или чисел).'
    )


def parse_channel_ids(text: str) -> list[str]:
    """Достать JSON-массив id из ответа движка (терпимо к преамбуле/обёртке)."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = "\n".join(
            ln for ln in candidate.splitlines() if not ln.strip().startswith("```")
        )
    start, end = candidate.find("["), candidate.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()]


def classify_channels(
    engine: Engine, channels: list[dict[str, Any]]
) -> set[str]:
    """Множество id каналов, которые AI счёл «про вакансии» (один вызов движка)."""
    if not channels:
        return set()
    answer = engine.complete(build_classify_prompt(channels))
    return set(parse_channel_ids(answer))


# ── Интерактивный логин (async Telethon за фабрикой) ─────────────────────────

# (api_id, api_hash, session) -> Telethon-подобный клиент.
ClientFactory = Callable[[str, str, str], Any]

_PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{6,}$")


class TelegramLogin:  # pragma: no cover - async Telethon / реальная сеть
    """Стейтфул-логин: держит клиент Telethon между запросами на фоновом loop."""

    def __init__(
        self, envfile: Path | str, *, client_factory: ClientFactory | None = None
    ) -> None:
        import asyncio
        import threading

        self._envfile = Path(envfile)
        self._factory = client_factory or _default_factory
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self._client: Any = None
        self._qr: Any = None
        self._phone = ""
        self._code_hash = ""
        self._api_id = ""
        self._api_hash = ""

    def _run(self, coro: Any, timeout: float = 60.0) -> Any:
        import asyncio

        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def start(self, api_id: str, api_hash: str, phone: str) -> dict[str, object]:
        api_id, api_hash, phone = api_id.strip(), api_hash.strip(), phone.strip()
        if not (api_id and api_hash and phone):
            return {"ok": False, "message": "укажите api_id, api_hash и телефон"}
        if not _PHONE_RE.match(phone):
            return {"ok": False, "message": "телефон в формате +79991234567"}

        async def _go() -> tuple[Any, str, str]:
            client = self._factory(api_id, api_hash, "")
            await client.connect()
            sent = await client.send_code_request(phone)
            # Telegram сам решает КУДА слать код — отдаём это пользователю явно.
            return client, sent.phone_code_hash, type(sent.type).__name__

        try:
            client, code_hash, code_type = self._run(_go())
        except Exception as exc:
            return {"ok": False, "message": _clean_err(exc)}
        self._client, self._phone, self._code_hash = client, phone, code_hash
        self._api_id, self._api_hash = api_id, api_hash
        where = {
            "SentCodeTypeApp": "СООБЩЕНИЕМ в приложение Telegram (от аккаунта "
            "«Telegram») — открой Telegram на телефоне, код там, НЕ в SMS",
            "SentCodeTypeSms": "по SMS на твой номер",
            "SentCodeTypeCall": "звонком на номер — продиктуют код",
            "SentCodeTypeFlashCall": "звонком (введи последние цифры номера)",
            "SentCodeTypeMissedCall": "пропущенным звонком (код — последние цифры "
            "номера, с которого звонят)",
        }.get(code_type, "в Telegram")
        return {
            "ok": True,
            "stage": "code",
            "message": f"Код отправлен {where}. Введи его ниже.",
        }

    def qr_start(self, api_id: str, api_hash: str) -> dict[str, object]:
        """Начать вход по QR-коду: код не нужен, пользователь сканирует QR из
        приложения Telegram (Настройки → Устройства → Подключить устройство)."""
        api_id, api_hash = api_id.strip(), api_hash.strip()
        if not (api_id and api_hash):
            return {"ok": False, "message": "сначала укажи api_id и api_hash"}

        async def _go() -> tuple[Any, Any]:
            client = self._factory(api_id, api_hash, "")
            await client.connect()
            qr = await client.qr_login()
            return client, qr

        try:
            client, qr = self._run(_go())
        except Exception as exc:
            return {"ok": False, "message": _clean_err(exc)}
        self._client, self._qr = client, qr
        self._api_id, self._api_hash = api_id, api_hash
        return {
            "ok": True,
            "stage": "qr",
            "qr": qr_data_uri(qr.url),
            "message": "В приложении Telegram: Настройки → Устройства → "
            "«Подключить устройство» → наведи камеру на QR.",
        }

    def qr_poll(self) -> dict[str, object]:
        """Опросить статус QR-входа. Возвращает обновлённый QR (если токен
        протух), запрос 2FA-пароля или завершение входа."""
        if self._client is None or self._qr is None:
            return {"ok": False, "message": "QR-вход не начат"}
        from telethon.errors import SessionPasswordNeededError

        async def _go() -> tuple[str, str | None]:
            # 2FA-аккаунт: после скана сервер требует пароль — и это всплывает не
            # только из wait(), но и из recreate() (он зовёт ExportLoginToken).
            # Поэтому ловим SessionPasswordNeededError вокруг ОБОИХ вызовов.
            try:
                try:
                    await self._qr.wait(timeout=3)
                    return "ok", None
                except TimeoutError:
                    # Токен живёт ~30с — пересоздаём и отдаём свежий QR.
                    await self._qr.recreate()
                    return "wait", self._qr.url
            except SessionPasswordNeededError:
                return "password", None

        try:
            state, url = self._run(_go(), timeout=20.0)
        except Exception as exc:
            return {"ok": False, "message": _clean_err(exc)}
        if state == "password":
            return {"ok": True, "stage": "password", "message": "введите пароль 2FA"}
        if state == "wait":
            return {"ok": True, "stage": "qr", "qr": qr_data_uri(url or "")}
        return self._finish()

    def import_session(
        self, api_id: str, api_hash: str, session: str
    ) -> dict[str, object]:
        """Принять готовую строку сессии Telethon (полученную где-то ещё) —
        проверяем, что она действительна, и сохраняем. Кода не требуется."""
        api_id, api_hash, session = api_id.strip(), api_hash.strip(), session.strip()
        if not session:
            return {"ok": False, "message": "вставь строку сессии"}
        if not (api_id and api_hash):
            return {
                "ok": False,
                "message": "нужны api_id и api_hash — та же пара, на которой "
                "сессия была создана",
            }

        async def _go() -> tuple[Any, bool]:
            client = self._factory(api_id, api_hash, session)
            await client.connect()
            return client, await client.is_user_authorized()

        try:
            client, authorized = self._run(_go())
        except Exception as exc:
            return {"ok": False, "message": _clean_err(exc)}
        if not authorized:
            try:
                self._run(client.disconnect())
            except Exception:
                pass
            return {
                "ok": False,
                "message": "сессия недействительна (или не та пара api_id/api_hash)",
            }
        self._client = client
        self._api_id, self._api_hash = api_id, api_hash
        return self._finish()

    def submit_code(self, code: str) -> dict[str, object]:
        if self._client is None:
            return {"ok": False, "message": "сначала запросите код"}
        from telethon.errors import SessionPasswordNeededError

        async def _go() -> str:
            try:
                await self._client.sign_in(
                    self._phone, code.strip(), phone_code_hash=self._code_hash
                )
                return "ok"
            except SessionPasswordNeededError:
                return "password"

        try:
            res = self._run(_go())
        except Exception as exc:
            return {"ok": False, "message": _clean_err(exc)}
        if res == "password":
            return {"ok": True, "stage": "password", "message": "введите пароль 2FA"}
        return self._finish()

    def submit_password(self, password: str) -> dict[str, object]:
        if self._client is None:
            return {"ok": False, "message": "сессия входа не начата"}

        async def _go() -> None:
            await self._client.sign_in(password=password)

        try:
            self._run(_go())
        except Exception as exc:
            return {"ok": False, "message": _clean_err(exc)}
        return self._finish()

    def _finish(self) -> dict[str, object]:
        session = self._client.session.save()
        merge_env(
            self._envfile,
            {
                "TELEGRAM_API_ID": self._api_id,
                "TELEGRAM_API_HASH": self._api_hash,
                "TELEGRAM_SESSION": session,
            },
        )
        try:
            self._run(self._client.disconnect())
        except Exception:
            pass
        self._client = None
        self._qr = None
        return {"ok": True, "stage": "done", "message": "вход выполнен"}

    def list_channels(
        self, api_id: str, api_hash: str, session: str
    ) -> list[dict[str, Any]]:
        """Каналы пользователя (id, title, username) по сохранённой сессии."""
        if not session:
            return []

        async def _go() -> list[dict[str, Any]]:
            client = self._factory(api_id, api_hash, session)
            await client.connect()
            out: list[dict[str, Any]] = []
            try:
                async for dialog in client.iter_dialogs():
                    if not getattr(dialog, "is_channel", False):
                        continue
                    ent = dialog.entity
                    username = getattr(ent, "username", None)
                    # Только каналы с username — их надёжно резолвит сбор; каналы
                    # без публичного имени по голому id Telethon не открывает.
                    if not username:
                        continue
                    if getattr(ent, "broadcast", False) or getattr(ent, "megagroup", False):
                        out.append(
                            {
                                "id": username,
                                "title": getattr(ent, "title", "") or "",
                                "username": username,
                            }
                        )
            finally:
                await client.disconnect()
            return out

        try:
            return self._run(_go(), timeout=120.0)
        except Exception:
            return []


def _default_factory(api_id: str, api_hash: str, session: str) -> Any:  # pragma: no cover
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    return TelegramClient(StringSession(session), int(api_id), api_hash)


def _clean_err(exc: Exception) -> str:  # pragma: no cover
    msg = str(exc) or type(exc).__name__
    return msg[:200]
