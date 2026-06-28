"""HTML-разметка экранов web-UI (серверный рендер, без шаблонизатора).

`render_settings()` — Экран 1 «Настройка» (Task 5.1). Структура обобщена под
`tracks[]`: вместо двух фиксированных колонок прототипа — повторяемая карточка
направления (`track_card`) + `<template>` для клонирования в браузере.

`render_results()` — Экран 2 «Подборка» (Task 5.2): шапка прогона со статистикой
и кнопкой скачивания `.xlsx`, ниже — карточки вакансий по убыванию `overall`.
Тег направления скрыт при единственном треке; кнопка «Сопроводительное» — только
при `overall >= cover_letter_threshold` и наличии письма. Цвета и иконки идут
только из `webui.components` (поверх `job_agent.presentation`).
"""

from __future__ import annotations

from collections.abc import Iterable
from html import escape

from job_agent.models import EnrichedResult
from job_agent.presentation import DEFAULT_AMBER_MIN, DEFAULT_GREEN_MIN
from webui.components import badge, icon, status_pill, track_tag, verdict_line

__all__ = [
    "render_settings",
    "render_engine",
    "path_field",
    "track_card",
    "save_result_page",
    "vacancy_card",
    "render_results",
    "render_run",
]

#: Дефолтное число карточек подборки за прогон (топ по overall).
DEFAULT_TOP_K = 15


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


def path_field(
    *, name: str, label_html: str, placeholder: str, kind: str, accept: str = ""
) -> str:
    """Поле-путь к файлу с кнопкой «Загрузить» рядом.

    Текстовый `input` (путь) + кнопка, которая через JS (`settings.js`) шлёт
    выбранный файл на `/upload` и подставляет вернувшийся относительный путь.
    `kind` — тип файла (resume/template/search_map), решает подпапку на сервере.
    Скрытый `file`-input лежит соседом кнопки в `.path-input`, чтобы работать и в
    клонированных карточках направления (поиск идёт по соседям, не по `name`).
    """
    acc = f' accept="{accept}"' if accept else ""
    return (
        '<div class="field"><span class="field__label">'
        + label_html
        + "</span>"
        '<div class="path-input">'
        f'<input class="input" name="{name}" placeholder="{placeholder}">'
        f'<button type="button" class="btn btn--ghost file-upload" data-kind="{kind}">'
        f'{icon("ti-upload")} Загрузить</button>'
        f'<input type="file" class="file-upload__input" hidden{acc}>'
        "</div>"
        '<span class="path-input__status" aria-live="polite"></span>'
        "</div>"
    )


def track_card(*, removable: bool = True) -> str:
    """Одна повторяемая карточка направления (имя · резюме · шаблон · роли).

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
        + path_field(
            name="track_resume",
            label_html=f'{icon("ti-file-cv")} Резюме (путь к файлу)',
            placeholder="./resumes/backend.pdf",
            kind="resume",
            accept=".pdf,.txt,.md",
        )
        + path_field(
            name="track_template",
            label_html=f'{icon("ti-mail")} Шаблон сопроводительного · пример (опц.)',
            placeholder="./cover-templates/default.pdf",
            kind="template",
            accept=".pdf,.txt,.md",
        )
        +
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
        + path_field(
            name="search_map_path",
            label_html=f'{icon("ti-map-2")} Карта поиска · общая',
            placeholder="./search-map.md — примеры идеальных вакансий",
            kind="search_map",
            accept=".pdf,.md,.txt,.json",
        )
        + "</div>"
    )
    return (
        '<section class="card">'
        f'<div class="card__title">{icon("ti-user")} Профиль</div>'
        '<div class="card__meta">Одно или несколько направлений. Каждое '
        "самодостаточно: своё резюме и шаблон.</div>"
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


def _engine_pointer() -> str:
    """Указатель на отдельную страницу настройки движка/авторизации."""
    return (
        '<section class="card">'
        f'<div class="card__title">{icon("ti-cpu")} Движок AI</div>'
        '<div class="card__meta">Выбор движка (Claude / Codex / Ollama / свой ключ), '
        "авторизация и web-поиск — на отдельной странице.</div>"
        '<a class="btn btn--ghost" href="/engine">'
        f'{icon("ti-arrow-right")} Открыть «AI · авторизация»</a>'
        "</section>"
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
        + _engine_pointer()
        + _output_card()
        + _footer()
        + "</form>"
    )


# ── Экран «AI · авторизация» ───────────────────────────────────────


def _engine_choice(value: str, title: str, meta: str, badge_text: str, *, active: bool) -> str:
    """Радио-карточка выбора движка с пометкой биллинга (подписка/бесплатно)."""
    checked = " checked" if active else ""
    return (
        '<label class="engine-card">'
        f'<input type="radio" name="engine" value="{value}"{checked}>'
        f'<span class="engine-card__title">{title}'
        f'<span class="badge-default">{escape(badge_text)}</span></span>'
        f'<span class="engine-card__meta">{escape(meta)}</span>'
        "</label>"
    )


def _copy_cmd(cmd: str) -> str:
    """Команда с кнопкой «копировать» (JS пишет в буфер; без CDN)."""
    return (
        f'<span class="cmd"><code>{escape(cmd)}</code>'
        f'<button type="button" class="copy-cmd" data-copy="{escape(cmd)}" '
        f'title="копировать">{icon("ti-copy")}</button></span>'
    )


def _login_widget(engine: str) -> str:
    """Кнопка «Войти» + место для ссылки и формы кода (наполняет login.js)."""
    return (
        f'<div class="login-flow" data-login="{engine}">'
        f'<button type="button" class="btn btn--accent login-start" '
        f'data-engine="{engine}">{icon("ti-login-2")} Войти через браузер</button>'
        f'<div class="login-flow__out" data-login-out="{engine}"></div>'
        "</div>"
    )


def _auth_panel(
    key: str,
    title: str,
    hint_html: str,
    fields_html: str,
    *,
    visible: bool = False,
    with_test: bool = True,
) -> str:
    """Панель авторизации движка: статус-пилюли (JS заполнит) + поля/подсказки.

    Видна только панель выбранного движка (`visible`); остальные скрыты —
    JS переключает по выбору радио. Так UI показывает настройку и статус только
    для текущего движка, а не все сразу.
    """
    hidden = "" if visible else " hidden"
    test = (
        '<button type="button" class="btn engine-test" '
        f'data-engine="{key}">{icon("ti-plug-connected")} Проверить</button>'
        f'<span class="path-input__status" data-test="{key}"></span>'
        if with_test
        else ""
    )
    return (
        f'<div class="auth-panel" data-engine="{key}"{hidden}>'
        f'<div class="auth-panel__head"><span class="auth-panel__title">{escape(title)}</span>'
        f'<span class="auth-panel__status" data-status="{key}">'
        f'{status_pill(ok=False, text="проверяю…", unknown=True)}</span></div>'
        f'<div class="auth-panel__hint">{hint_html}</div>'
        f"{fields_html}{test}"
        "</div>"
    )


def render_engine(
    *,
    scoring_engine: str = "cli",
    cli_tool: str = "codex",
    ollama_model: str = "",
    has_ollama_key: bool = False,
) -> str:
    """Экран «AI · авторизация»: выбор движка, статус, авторизация, web-поиск.

    Два движка: Codex (вход через ChatGPT) и Ollama Cloud (ключ + модель).
    Видна панель только выбранного движка; статусы заполняет JS из `/engine/status`.
    Секреты в значения полей не подставляются — только пометка «уже задан».
    """
    active = (
        cli_tool if scoring_engine == "cli" else scoring_engine
    )  # codex|ollama
    if active not in ("codex", "ollama"):
        active = "codex"

    choices = (
        _engine_choice("codex", "Codex", "вход через ChatGPT", "подписка",
                       active=active == "codex")
        + _engine_choice("ollama", "Ollama Cloud", "облачные модели", "нужен ключ",
                         active=active == "ollama")
    )

    def secret_field(name: str, label: str, placeholder: str, *, has: bool) -> str:
        note = ' <span class="hint-set">уже задан ✓</span>' if has else ""
        return (
            f'<label class="field"><span class="field__label">{label}{note}</span>'
            f'<input class="input" type="password" name="{name}" placeholder="{placeholder}">'
            "</label>"
        )

    codex_panel = _auth_panel(
        "codex",
        "Codex — вход через ChatGPT (без API-ключа)",
        "Вход в один клик: сервер запустит <code>codex login --device-auth</code>, "
        "покажет ссылку и одноразовый код — откройте ссылку, введите код в браузере "
        "(аккаунт ChatGPT), затем нажмите «Я ввёл код»."
        + _login_widget("codex"),
        "",  # codex авторизуется по входу ChatGPT, поля ключа нет
        visible=active == "codex",
    )
    # Текущая модель — первой опцией списка (JS дозаполнит реальными с сервера).
    model_opts = (
        f'<option value="{escape(ollama_model)}" selected>{escape(ollama_model)}</option>'
        if ollama_model
        else '<option value="" selected>— загрузите модели —</option>'
    )
    ollama_panel = _auth_panel(
        "ollama",
        "Ollama Cloud — облачные модели",
        "Ключ — на " + _copy_cmd("ollama.com/settings/keys") + ". Вставьте его, "
        "нажмите «Загрузить модели» и выберите модель.",
        secret_field("ollama_key", "OLLAMA_API_KEY", "вставьте ключ облака",
                     has=has_ollama_key)
        + '<button type="button" class="btn ollama-load">'
        f'{icon("ti-refresh")} Загрузить модели</button>'
        '<span class="path-input__status" data-ollama-load></span>'
        '<label class="field"><span class="field__label">Модель</span>'
        f'<select class="input" name="ollama_model" data-ollama-model-select>{model_opts}'
        "</select></label>",
        visible=active == "ollama",
        with_test=False,  # у Ollama своя кнопка «Загрузить модели» вместо «Проверить»
    )

    return (
        _engine_header()
        + '<form method="post" action="/engine/save">'
        '<section class="card">'
        f'<div class="card__title">{icon("ti-cpu")} Движок AI</div>'
        f'<div class="engine-grid">{choices}</div>'
        f"{codex_panel}{ollama_panel}"
        "</section>"
        + '<div class="form-footer">'
        '<button type="submit" class="btn btn--accent">Сохранить</button></div>'
        "</form>"
    )


def _engine_header() -> str:
    return (
        '<div class="app-header">'
        f'<span class="app-header__icon">{icon("ti-cpu")}</span>'
        '<div><div class="card__title">AI · авторизация</div>'
        '<div class="card__meta">движок скоринга и доступ к нему — локально</div></div>'
        "</div>"
    )


def render_run() -> str:
    """Страница «Прогон»: статус backfill (наполняет run.js опросом /run/status)."""
    return (
        '<div class="app-header">'
        f'<span class="app-header__icon">{icon("ti-player-play")}</span>'
        '<div><div class="card__title">Прогон backfill</div>'
        '<div class="card__meta">сбор → фильтр → скоринг → .xlsx</div></div>'
        "</div>"
        '<section class="card"><div class="run-status" data-run-status>'
        f'{icon("ti-loader")} запускаю…</div></section>'
        '<p><a href="/">← к настройке</a> · <a href="/results">подборка</a></p>'
    )


# ── Экран 2 «Подборка» (Task 5.2) ─────────────────────────────────


def _open_target(result: EnrichedResult) -> str:
    """Куда ведёт «Открыть»: ссылка/контакт вакансии, иначе её url."""
    vacancy = result.vacancy
    return vacancy.link_or_contact or vacancy.url or ""


def _gap_line(result: EnrichedResult) -> str:
    """Один наиболее важный гэп: критичный → стратегический → косметический."""
    gaps = result.score.gaps
    for items in (gaps.critical, gaps.strategic, gaps.cosmetic):
        if items:
            return items[0]
    return ""


def _meta_line(result: EnrichedResult) -> str:
    """«компания · стадия · формат» — из того, что есть (стадия = анализ компании)."""
    parts = [
        p
        for p in (result.vacancy.company, result.score.company_analysis)
        if p
    ]
    return " · ".join(parts)


def _card_buttons(
    result: EnrichedResult,
    *,
    overall: int,
    cover_letter_threshold: int,
) -> str:
    """Кнопки карточки: «Открыть» · «Сопроводительное» (условно) · «Контакт»."""
    buttons: list[str] = []

    target = _open_target(result)
    if target:
        buttons.append(
            f'<a class="btn" href="{escape(target)}" target="_blank" rel="noopener">'
            f'{icon("ti-external-link")} Открыть</a>'
        )

    # «Сопроводительное» — только выше порога и при наличии письма.
    if overall >= cover_letter_threshold and result.cover_letter:
        buttons.append(
            f'<button type="button" class="btn">{icon("ti-copy")} '
            "Сопроводительное</button>"
        )

    # «Контакт + обращение» — только когда контакт-ассист отработал.
    if result.contacts is not None:
        buttons.append(
            f'<button type="button" class="btn">{icon("ti-user-search")} '
            "Контакт + обращение</button>"
        )

    return f'<div class="result-card__actions">{"".join(buttons)}</div>'


def vacancy_card(
    result: EnrichedResult,
    *,
    is_single_track: bool = False,
    cover_letter_threshold: int = 70,
    green_min: int = DEFAULT_GREEN_MIN,
    amber_min: int = DEFAULT_AMBER_MIN,
) -> str:
    """Одна карточка вакансии подборки.

    Тег направления добавляется только при `is_single_track == False`. Бейдж
    «резюме %», иконка/тон вердикта — из `webui.components` (поверх presentation).
    """
    vacancy = result.vacancy
    scores = result.score.scores
    overall = scores.overall

    tag = "" if is_single_track else track_tag(result.score.track)
    meta = _meta_line(result)
    meta_html = f'<div class="card__meta">{escape(meta)}</div>' if meta else ""

    right = (
        '<div class="result-card__right">'
        f"{badge(overall, green_min=green_min, amber_min=amber_min)}"
        f'<span class="result-card__map">{icon("ti-map-2")} карта '
        f"{scores.map_fit}%</span>"
        "</div>"
    )

    verdict = verdict_line(
        result.score.verdict.type,
        result.score.verdict.summary,
        overall=overall,
        amber_min=amber_min,
    )
    gap = _gap_line(result)
    gap_html = (
        f'<div class="result-card__gap">Гэп: {escape(gap)}</div>' if gap else ""
    )

    buttons = _card_buttons(
        result, overall=overall, cover_letter_threshold=cover_letter_threshold
    )

    return (
        '<div class="card result-card">'
        '<div class="result-card__head">'
        "<div>"
        f'<div class="card__title">{escape(vacancy.title)}</div>'
        f"{meta_html}"
        f"{tag}"
        "</div>"
        f"{right}"
        "</div>"
        f"{verdict}"
        f"{gap_html}"
        f"{buttons}"
        "</div>"
    )


def _run_header(
    *,
    run_date: str,
    collected: int,
    after_filter: int,
    shown: int,
    xlsx_href: str,
) -> str:
    title = f"Подборка · {escape(run_date)}" if run_date else "Подборка"
    stats = f"собрано {collected} · после фильтра {after_filter} · топ-{shown}"
    return (
        '<div class="run-header">'
        "<div>"
        f'<div class="card__title">{title}</div>'
        f'<div class="card__meta">{stats}</div>'
        "</div>"
        f'<a class="btn" href="{escape(xlsx_href)}" download>'
        f'{icon("ti-download")} Скачать .xlsx</a>'
        "</div>"
    )


def render_results(
    results: Iterable[EnrichedResult],
    *,
    run_date: str = "",
    collected: int | None = None,
    after_filter: int | None = None,
    is_single_track: bool = False,
    cover_letter_threshold: int = 70,
    top_k: int = DEFAULT_TOP_K,
    green_min: int = DEFAULT_GREEN_MIN,
    amber_min: int = DEFAULT_AMBER_MIN,
    xlsx_href: str = "/results.xlsx",
) -> str:
    """Экран 2 «Подборка» целиком: шапка прогона + карточки по убыванию overall.

    `collected`/`after_filter` для статистики шапки; при `None` берутся из числа
    результатов. Сорт по `overall` убыв., показываются топ-`top_k`.
    """
    ordered = sorted(
        results, key=lambda r: r.score.scores.overall, reverse=True
    )
    selected = ordered[:top_k] if top_k > 0 else ordered

    total = len(ordered)
    header = _run_header(
        run_date=run_date,
        collected=total if collected is None else collected,
        after_filter=total if after_filter is None else after_filter,
        shown=len(selected),
        xlsx_href=xlsx_href,
    )

    if not selected:
        empty = (
            '<div class="notice-warning">'
            f"{icon('ti-alert-triangle')} Прогон ещё не выполнялся — "
            "запустите backfill на экране настройки."
            "</div>"
        )
        return header + empty

    cards = "".join(
        vacancy_card(
            r,
            is_single_track=is_single_track,
            cover_letter_threshold=cover_letter_threshold,
            green_min=green_min,
            amber_min=amber_min,
        )
        for r in selected
    )
    return header + f'<div class="results-list">{cards}</div>'


def save_result_page(
    *,
    ok: bool,
    action: str = "save",
    path: str = "",
    message: str = "",
    note_html: str = "",
    back_href: str = "/",
    back_label: str = "вернуться к настройке",
    verify_engine: str = "",
) -> str:
    """Страница-подтверждение после сабмита формы.

    `note_html` — доверенная HTML-подсказка (строится маршрутом, напр. про
    перезапуск стека после смены ключа). `back_href`/`back_label` — ссылка назад.
    `verify_engine` — если задан, страница сразу гоняет «Проверить» для движка
    (engine.js ловит `data-autoverify`), показывая результат пробы инлайн.
    """
    back = f'<p><a href="{escape(back_href)}">← {escape(back_label)}</a></p>'
    if not ok:
        return (
            '<div class="notice-warning">'
            f"{icon('ti-alert-triangle')} Конфиг не сохранён: {escape(message)}"
            f"</div>{back}"
        )
    started = (
        " Backfill запускается — следите за логами."
        if action == "backfill"
        else ""
    )
    note = f'<div class="card__meta">{note_html}</div>' if note_html else ""
    verify = (
        f'<div class="autoverify" data-autoverify="{escape(verify_engine)}">'
        f'{icon("ti-plug-connected")} Проверяю движок…</div>'
        if verify_engine
        else ""
    )
    return (
        '<div class="card">'
        f'<div class="card__title">{icon("ti-circle-check")} Конфиг сохранён</div>'
        f'<div class="card__meta">{escape(path)}.{started}</div>'
        f"{note}{verify}"
        f"</div>{back}"
    )
