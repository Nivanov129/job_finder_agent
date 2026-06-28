"""HTML-разметка экранов web-UI (серверный рендер, без шаблонизатора).

`render_settings()` — Экран 1 «Настройка» (Task 5.1). Структура обобщена под
`tracks[]`: вместо двух фиксированных колонок прототипа — повторяемая карточка
направления (`track_card`) + `<template>` для клонирования в браузере. Цвета и
иконки идут только из `webui.components` (поверх `job_agent.presentation`).
"""

from __future__ import annotations

from webui.components import icon

__all__ = ["render_settings", "track_card", "save_result_page"]


def _header() -> str:
    return (
        '<div class="app-header">'
        f'<span class="app-header__icon">{icon("ti-radar-2")}</span>'
        '<div><div class="card__title">Job agent · настройка</div>'
        '<div class="card__meta">локально на вашем компьютере</div></div>'
        "</div>"
    )


def _warning() -> str:
    return (
        '<div class="notice-warning">'
        f"{icon('ti-alert-triangle')} Ночной мониторинг требует постоянно "
        "включённого хоста (always-on). Backfill можно запускать вручную."
        "</div>"
    )


def track_card(*, removable: bool = True) -> str:
    """Одна повторяемая карточка направления (имя · резюме · шаблон · рубрика · роли).

    Используется и для серверного рендера первой карточки, и как тело `<template>`
    для клонирования по «+ добавить направление».
    """
    remove = (
        f'<button type="button" class="btn-icon track-remove" '
        f'aria-label="Удалить направление">{icon("ti-trash")}</button>'
        if removable
        else ""
    )
    return (
        '<div class="track-card panel">'
        '<div class="track-card__head">'
        '<span class="track-tag">направление</span>'
        f"{remove}"
        "</div>"
        '<label class="field"><span class="field__label">Имя направления</span>'
        '<input class="input" name="track_name" placeholder="напр. Backend"></label>'
        f'<label class="field"><span class="field__label">{icon("ti-file-cv")} '
        'Резюме (путь к файлу)</span>'
        '<input class="input" name="track_resume" placeholder="./resumes/backend.pdf"></label>'
        f'<label class="field"><span class="field__label">{icon("ti-mail")} '
        'Шаблон сопроводительного · пример (опц.)</span>'
        '<input class="input" name="track_template" '
        'placeholder="./cover-templates/default.md"></label>'
        '<label class="field"><span class="field__label">Рубрика — «что для меня '
        'попадание» (опц.)</span>'
        '<textarea class="input" name="track_rubric" rows="2"></textarea></label>'
        '<label class="field"><span class="field__label">Допустимые роли (опц., '
        'через запятую)</span>'
        '<input class="input" name="track_roles" '
        'placeholder="Product Manager, Head of Product"></label>'
        "</div>"
    )


def _profile_card() -> str:
    # Заголовок «Профиль» (без «под два пути» — устаревшая модель прототипа).
    tpl = (
        '<template id="track-template">' + track_card(removable=True) + "</template>"
    )
    search_map = (
        '<div class="panel panel--dashed">'
        f'<div class="field__label">{icon("ti-map-2")} Карта поиска · общая</div>'
        '<input class="input" name="search_map_path" '
        'placeholder="./search-map.md — примеры идеальных вакансий"></div>'
    )
    return (
        '<section class="card">'
        f'<div class="card__title">{icon("ti-user")} Профиль</div>'
        '<div class="card__meta">Одно или несколько направлений. Каждое '
        "самодостаточно: своё резюме, шаблон и рубрика.</div>"
        '<div id="tracks-list" class="tracks-grid">' + track_card(removable=True) + "</div>"
        '<button type="button" class="btn btn--ghost" id="add-track">'
        f'{icon("ti-plus")} Добавить направление</button>'
        + search_map
        + tpl
        + "</section>"
    )


def _sources_card() -> str:
    return (
        '<section class="card">'
        f'<div class="card__title">{icon("ti-rss")} Источники</div>'
        '<label class="field"><span class="field__label">Telegram-каналы '
        "(по одному в строке)</span>"
        '<textarea class="input" name="channels" rows="3" '
        'placeholder="@ml_jobs&#10;@product_jobs"></textarea></label>'
        '<div class="field__label">Агрегаторы</div>'
        '<label class="chip-toggle"><input type="checkbox" name="use_aggregators" checked>'
        f'<span class="chip chip--on">{icon("ti-rss")} vseti.app</span>'
        f'<span class="chip chip--on">{icon("ti-rss")} getmatch</span></label>'
        "</section>"
    )


def _engine_card() -> str:
    def opt(value: str, title: str, meta: str, *, default: bool = False) -> str:
        checked = " checked" if default else ""
        badge = '<span class="badge-default">дефолт</span>' if default else ""
        return (
            '<label class="engine-card">'
            f'<input type="radio" name="engine" value="{value}"{checked}>'
            f'<span class="engine-card__title">{title}{badge}</span>'
            f'<span class="engine-card__meta">{meta}</span>'
            "</label>"
        )

    cards = (
        opt("cli", "CLI на подписке", "Claude Code / Codex", default=True)
        + opt("api_key", "Свой ключ", "Anthropic / OpenAI")
        + opt("ollama", "Ollama", "локальная модель")
    )
    extra = (
        '<input class="input" name="cli_tool" placeholder="claude или codex (для CLI)">'
        '<input class="input" name="api_base_url" placeholder="API base URL (для ключа)">'
        '<input class="input" name="api_key" type="password" placeholder="API ключ (секрет)">'
        '<input class="input" name="ollama_model" placeholder="llama3.1:70b (для Ollama)">'
    )
    web = (
        '<div class="field__label">Web-поиск</div>'
        '<input class="input" name="web_search_url" '
        'placeholder="http://localhost:8080 — SearXNG self-host">'
    )
    return (
        '<section class="card">'
        f'<div class="card__title">{icon("ti-cpu")} Движок AI</div>'
        f'<div class="engine-grid">{cards}</div>'
        f'<div class="engine-extra">{extra}</div>'
        + web
        + "</section>"
    )


def _output_card() -> str:
    return (
        '<section class="card">'
        f'<div class="card__title">{icon("ti-arrow-bar-to-down")} Выхлоп</div>'
        '<div class="field__label">Куда выгружать</div>'
        '<label class="chip-toggle"><input type="checkbox" name="out_table" checked>'
        f'<span class="chip chip--on">{icon("ti-table")} Таблица .xlsx</span></label>'
        '<label class="chip-toggle"><input type="checkbox" name="out_bot" checked>'
        f'<span class="chip chip--on">{icon("ti-brand-telegram")} Telegram-бот</span></label>'
        '<label class="field"><span class="field__label">Telegram bot token (секрет)</span>'
        '<input class="input" name="bot_token" type="password" placeholder="от @BotFather">'
        "</label>"
        '<label class="field"><span class="field__label">Сопроводительное — порог '
        '<output id="threshold-val">70%</output></span>'
        '<input type="range" class="slider" name="cover_threshold" min="0" max="100" '
        'value="70" oninput="document.getElementById(&#39;threshold-val&#39;).value='
        "this.value+&#39;%&#39;\"></label>"
        '<label class="chip-toggle"><input type="checkbox" name="enable_contacts">'
        '<span class="chip">Контакт-ассист (черновик, без отправки)</span></label>'
        "</section>"
    )


def _footer() -> str:
    return (
        '<div class="form-footer">'
        '<button type="submit" name="action" value="save" class="btn">Сохранить</button>'
        '<button type="submit" name="action" value="backfill" class="btn btn--accent">'
        f'{icon("ti-player-play")} Запустить backfill</button>'
        "</div>"
    )


def render_settings() -> str:
    """Экран 1 «Настройка» целиком (форма POST → /save)."""
    return (
        _header()
        + _warning()
        + '<form method="post" action="/save">'
        + _profile_card()
        + _sources_card()
        + _engine_card()
        + _output_card()
        + _footer()
        + "</form>"
    )


def save_result_page(*, ok: bool, action: str = "save", path: str = "", message: str = "") -> str:
    """Страница-подтверждение после сабмита формы."""
    if not ok:
        return (
            '<div class="notice-warning">'
            f"{icon('ti-alert-triangle')} Конфиг не сохранён: {message}"
            '</div><p><a href="/">← вернуться к настройке</a></p>'
        )
    started = (
        " Backfill запускается — следите за логами."
        if action == "backfill"
        else ""
    )
    return (
        '<div class="card">'
        f'<div class="card__title">{icon("ti-circle-check")} Конфиг сохранён</div>'
        f'<div class="card__meta">{path}.{started}</div>'
        '</div><p><a href="/">← вернуться к настройке</a></p>'
    )
