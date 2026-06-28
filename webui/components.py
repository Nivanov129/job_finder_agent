"""Общие HTML-компоненты web-UI: бейдж, чип, карточка.

Цветовое кодирование берётся ТОЛЬКО из `job_agent.presentation` (единственный
источник). Здесь — разметка; цвета прокидываются инлайном CSS-переменными
`--badge-bg/--badge-fg`, геометрия — в `static/css/components.css`.

Эти примитивы переиспользуют экраны Task 5.1 (настройка) и Task 5.2 (подборка).
"""

from __future__ import annotations

from html import escape

from job_agent.presentation import (
    DEFAULT_AMBER_MIN,
    DEFAULT_GREEN_MIN,
    TRACK_TAG_COLORS,
    badge_colors,
    verdict_style,
)

__all__ = [
    "badge",
    "track_tag",
    "chip",
    "card",
    "icon",
    "verdict_line",
    "nav",
    "status_pill",
]

#: Пункты бокового меню: (маршрут, иконка, подпись) или None — разделитель.
NAV_ITEMS: tuple[tuple[str, str, str] | None, ...] = (
    ("/agent", "ti-radar-2", "Агент"),
    ("/run", "ti-history-toggle", "Подбор за период"),
    ("/results", "ti-layout-grid", "Подборка"),
    None,
    ("/", "ti-adjustments", "Настройка"),
    ("/engine", "ti-cpu", "AI · авторизация"),
    ("/telegram", "ti-brand-telegram", "Telegram"),
)


def nav(active: str = "") -> str:
    """Левый сайдбар: бренд + карточка хоста (агент) + меню + кнопка паузы.

    `active` — текущий маршрут, его пункт подсвечивается. Карточку агента и
    кнопку паузы наполняет `app.js` опросом `/agent/status`.
    """
    items = ""
    for it in NAV_ITEMS:
        if it is None:
            items += '<div class="nav__divider"></div>'
            continue
        path, ic, label = it
        cls = "nav__item nav__item--active" if path == active else "nav__item"
        items += f'<a class="{cls}" href="{path}">{icon(ic)}<span>{escape(label)}</span></a>'
    return (
        '<aside class="sidebar">'
        '<div class="brand">'
        f'<div class="brand__logo">{icon("ti-radar-2")}</div>'
        '<div><div class="brand__name">Job Agent</div>'
        '<div class="brand__sub">локально · ваш компьютер</div></div>'
        "</div>"
        '<div class="host-card">'
        '<div class="host-card__row"><span class="orb" data-agent-orb></span>'
        '<span class="host-card__text" data-agent-host>хост · проверяю…</span></div>'
        '<div class="host-card__sub" data-agent-hostsub></div>'
        "</div>"
        f'<nav class="nav">{items}</nav>'
        '<div class="sidebar__foot">'
        '<button type="button" class="btn-pause agent-toggle" data-agent-pause>'
        f'{icon("ti-player-pause")} <span>Пауза</span></button></div>'
        "</aside>"
    )


def status_pill(*, ok: bool, text: str, unknown: bool = False) -> str:
    """Пилюля статуса (ок/нет/неизвестно) для карточек авторизации."""
    state = "unknown" if unknown else ("ok" if ok else "bad")
    glyph = {"ok": "ti-circle-check", "bad": "ti-circle-x", "unknown": "ti-circle-dashed"}[state]
    return f'<span class="pill pill--{state}">{icon(glyph)} {escape(text)}</span>'


def icon(name: str) -> str:
    """Иконка Tabler (локальный webfont). `name` — класс вида `ti-radar-2`."""
    return f'<i class="ti {escape(name)}" aria-hidden="true"></i>'


def badge(
    overall: int,
    *,
    green_min: int = DEFAULT_GREEN_MIN,
    amber_min: int = DEFAULT_AMBER_MIN,
    label: str = "резюме",
) -> str:
    """Бейдж «резюме %» — фон/текст по диапазону из `presentation.badge_colors`."""
    colors = badge_colors(overall, green_min=green_min, amber_min=amber_min)
    style = f"--badge-bg:{colors.bg};--badge-fg:{colors.fg}"
    return (
        f'<span class="badge" style="{style}">'
        f'<span class="badge__label">{escape(label)}</span>'
        f"<span class=\"badge__pct\">{int(overall)}%</span>"
        f"</span>"
    )


def track_tag(name: str) -> str:
    """Тег направления. Вызывающий сам решает скрывать ли при единственном треке."""
    style = f"--badge-bg:{TRACK_TAG_COLORS.bg};--badge-fg:{TRACK_TAG_COLORS.fg}"
    return f'<span class="track-tag" style="{style}">{escape(name)}</span>'


def chip(text: str, *, on: bool = False, icon_name: str | None = None) -> str:
    """Чип (источник/выхлоп). `on` — выбранное состояние (акцентная заливка)."""
    cls = "chip chip--on" if on else "chip"
    inner = (icon(icon_name) if icon_name else "") + escape(text)
    return f'<span class="{cls}">{inner}</span>'


def verdict_line(
    verdict_type: str,
    text: str,
    *,
    overall: int | None = None,
    amber_min: int = DEFAULT_AMBER_MIN,
) -> str:
    """Строка вердикта: иконка+тон по `presentation.verdict_style`."""
    style = verdict_style(verdict_type, overall=overall, amber_min=amber_min)
    return (
        f'<div class="verdict" style="color:{style.tone_hex}">'
        f"{icon(style.icon)} {escape(text or style.label)}"
        f"</div>"
    )


def card(*, title: str, meta: str = "", body: str = "", right: str = "") -> str:
    """Универсальная карточка: заголовок + мета (left), произвольный `right`, тело."""
    head_right = f'<div class="card__right">{right}</div>' if right else ""
    meta_html = f'<div class="card__meta">{escape(meta)}</div>' if meta else ""
    body_html = f'<div class="card__body">{body}</div>' if body else ""
    return (
        '<div class="card">'
        '<div class="card__head" style="display:flex;justify-content:space-between;gap:12px">'
        f'<div><div class="card__title">{escape(title)}</div>{meta_html}</div>'
        f"{head_right}"
        "</div>"
        f"{body_html}"
        "</div>"
    )
