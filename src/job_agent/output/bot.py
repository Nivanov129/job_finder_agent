"""Telegram-бот выход (стадия 7): финалисты скоринга → карточки в личный чат.

Карточка — по разделу «Форматы выхлопа» плана:
`должность @ компания` · тег направления (только при треках>1) · бейдж «резюме %»
· «карта %» · строка вердикта (иконка по `verdict.type`) · строка гэпа · кнопки
«Открыть» / «Скопировать сопроводительное» (только при `overall ≥ порога` и
наличии письма) / «Контакт + обращение» (только при наличии контактов).

Цветовое кодирование и иконки берём из `presentation.py` (единый источник, не
дублируем). Сеть (Bot API) спрятана за фасадом `BotTransport`; в тестах его
подменяет фейк — юнит-тесты в сеть не ходят. Чистые функции `build_card`/
`render_digest` собирают состав карточек и кнопок, их и тестируем.

Инвариант: бот пишет **только в личный чат владельца** (`owner_chat_id`), без
авто-DM кому-либо ещё.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from ..models import EnrichedResult
from ..presentation import (
    DEFAULT_AMBER_MIN,
    DEFAULT_GREEN_MIN,
    badge_band,
    verdict_style,
)

__all__ = [
    "ButtonKind",
    "CardButton",
    "Card",
    "BotTransport",
    "build_card",
    "render_digest",
    "send_digest",
    "TelegramBotTransport",
]

ButtonKind = Literal["open", "cover", "contact"]

#: Дефолтное число карточек за прогон (топ по overall).
DEFAULT_TOP_K = 15


@dataclass(frozen=True)
class CardButton:
    """Кнопка карточки: подпись, иконка Tabler, тип действия и полезная нагрузка.

    `kind`:
    - `open` — открыть вакансию (`value` = ссылка/контакт);
    - `cover` — скопировать сопроводительное (`value` = текст письма);
    - `contact` — контакт + черновик обращения (`value` = черновик/первый контакт).
    """

    label: str
    icon: str
    kind: ButtonKind
    value: str


@dataclass(frozen=True)
class Card:
    """Готовая карточка: текст сообщения, диапазон бейджа и кнопки."""

    text: str
    band: str
    buttons: list[CardButton] = field(default_factory=list)


def _open_target(result: EnrichedResult) -> str:
    vacancy = result.vacancy
    return vacancy.link_or_contact or vacancy.url or ""


def _gap_line(result: EnrichedResult) -> str:
    """Один наиболее важный гэп: критичный → стратегический → косметический."""
    gaps = result.score.gaps
    for items in (gaps.critical, gaps.strategic, gaps.cosmetic):
        if items:
            return items[0]
    return ""


def _build_buttons(
    result: EnrichedResult,
    *,
    overall: int,
    cover_letter_threshold: int,
) -> list[CardButton]:
    buttons: list[CardButton] = []

    target = _open_target(result)
    if target:
        buttons.append(
            CardButton(label="Открыть", icon="ti-external-link", kind="open", value=target)
        )

    # «Скопировать сопроводительное» — только выше порога и при наличии письма.
    if overall >= cover_letter_threshold and result.cover_letter:
        buttons.append(
            CardButton(
                label="Скопировать сопроводительное",
                icon="ti-copy",
                kind="cover",
                value=result.cover_letter,
            )
        )

    # «Контакт + обращение» — только когда контакт-ассист отработал.
    if result.contacts is not None:
        contacts = result.contacts
        value = contacts.draft_message
        if not value and contacts.candidates:
            value = contacts.candidates[0].name
        buttons.append(
            CardButton(
                label="Контакт + обращение",
                icon="ti-user-search",
                kind="contact",
                value=value,
            )
        )

    return buttons


def build_card(
    result: EnrichedResult,
    *,
    is_single_track: bool = False,
    cover_letter_threshold: int = 70,
    green_min: int = DEFAULT_GREEN_MIN,
    amber_min: int = DEFAULT_AMBER_MIN,
) -> Card:
    """Собрать карточку из одного финалиста.

    Тег направления добавляется только при `is_single_track == False`. Иконка/тон
    вердикта и диапазон бейджа берутся из `presentation.py`.
    """
    vacancy = result.vacancy
    scores = result.score.scores
    overall = scores.overall

    band = badge_band(overall, green_min=green_min, amber_min=amber_min)
    vstyle = verdict_style(
        result.score.verdict.type, overall=overall, amber_min=amber_min
    )

    header = vacancy.title
    if vacancy.company:
        header = f"{vacancy.title} @ {vacancy.company}"

    lines: list[str] = [header]
    if not is_single_track:
        lines.append(f"#{result.score.track}")
    lines.append(f"резюме {overall}% · карта {scores.map_fit}%")
    lines.append(f"{vstyle.label}: {result.score.verdict.summary}")
    gap = _gap_line(result)
    if gap:
        lines.append(f"Гэп: {gap}")

    buttons = _build_buttons(
        result, overall=overall, cover_letter_threshold=cover_letter_threshold
    )
    return Card(text="\n".join(lines), band=band, buttons=buttons)


def render_digest(
    results: Iterable[EnrichedResult],
    *,
    is_single_track: bool = False,
    cover_letter_threshold: int = 70,
    top_k: int = DEFAULT_TOP_K,
    green_min: int = DEFAULT_GREEN_MIN,
    amber_min: int = DEFAULT_AMBER_MIN,
) -> list[Card]:
    """Карточки за прогон: сорт по `overall` убыв., топ-`top_k`."""
    ordered = sorted(results, key=lambda r: r.score.scores.overall, reverse=True)
    selected = ordered[:top_k] if top_k > 0 else ordered
    return [
        build_card(
            r,
            is_single_track=is_single_track,
            cover_letter_threshold=cover_letter_threshold,
            green_min=green_min,
            amber_min=amber_min,
        )
        for r in selected
    ]


class BotTransport(ABC):
    """Фасад отправки карточки в Telegram. В тестах подменяется фейком."""

    @abstractmethod
    def send_card(self, chat_id: int | str, card: Card) -> None:
        """Отправить одну карточку в указанный чат (личный чат владельца)."""
        raise NotImplementedError


def send_digest(
    results: Iterable[EnrichedResult],
    transport: BotTransport,
    owner_chat_id: int | str,
    *,
    is_single_track: bool = False,
    cover_letter_threshold: int = 70,
    top_k: int = DEFAULT_TOP_K,
    green_min: int = DEFAULT_GREEN_MIN,
    amber_min: int = DEFAULT_AMBER_MIN,
) -> list[Card]:
    """Отправить дайджест финалистов в личный чат владельца, вернуть карточки.

    Инвариант: единственный получатель — `owner_chat_id`. Никаких авто-DM никому
    другому. Топ по `overall`, состав карточки — `build_card`.
    """
    cards = render_digest(
        results,
        is_single_track=is_single_track,
        cover_letter_threshold=cover_letter_threshold,
        top_k=top_k,
        green_min=green_min,
        amber_min=amber_min,
    )
    for card in cards:
        transport.send_card(owner_chat_id, card)
    return cards


class TelegramBotTransport(BotTransport):  # pragma: no cover - реальная сеть
    """Реальный транспорт поверх Bot API (httpx). Секрет-токен не логируется.

    Кнопка «Открыть» становится url-кнопкой; «Скопировать сопроводительное» и
    «Контакт + обращение» — callback-кнопками (полезная нагрузка обрабатывается
    обработчиком бота на стороне владельца). Отправка только в `owner_chat_id`.
    """

    _API = "https://api.telegram.org"

    def __init__(self, bot_token: str, *, client: object | None = None) -> None:
        self._token = bot_token
        self._client = client

    def _keyboard(self, card: Card) -> dict[str, object]:
        rows: list[list[dict[str, str]]] = []
        for btn in card.buttons:
            if btn.kind == "open":
                rows.append([{"text": btn.label, "url": btn.value}])
            else:
                rows.append([{"text": btn.label, "callback_data": btn.kind}])
        return {"inline_keyboard": rows}

    def send_card(self, chat_id: int | str, card: Card) -> None:
        import httpx

        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": card.text,
            "reply_markup": self._keyboard(card),
        }
        url = f"{self._API}/bot{self._token}/sendMessage"
        client = self._client
        if client is None:
            with httpx.Client(timeout=30.0) as c:
                c.post(url, json=payload)
        else:
            client.post(url, json=payload)  # type: ignore[attr-defined]
