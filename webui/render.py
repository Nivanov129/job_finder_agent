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
    "render_agent",
    "render_results_screen",
    "render_telegram",
]

#: Дефолтное число карточек подборки за прогон (топ по overall).
DEFAULT_TOP_K = 15


def _warning() -> str:
    return (
        '<div class="notice-warning">'
        f"{icon('ti-alert-triangle')} Ночной мониторинг требует постоянно "
        "включённого хоста (always-on). Backfill можно запускать вручную."
        "</div>"
    )


def path_field(
    *, name: str, label_html: str, placeholder: str, kind: str, accept: str = "",
    value: str = "",
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
        f'<input class="input" name="{name}" placeholder="{placeholder}" '
        f'value="{escape(value)}">'
        f'<button type="button" class="btn btn--ghost file-upload" data-kind="{kind}">'
        f'{icon("ti-upload")} Загрузить</button>'
        f'<input type="file" class="file-upload__input" hidden{acc}>'
        "</div>"
        '<span class="path-input__status" aria-live="polite"></span>'
        "</div>"
    )


def track_card(
    *, removable: bool = True, name: str = "", resume: str = "",
    template: str = "", roles: str = "",
) -> str:
    """Одна повторяемая карточка направления (имя · резюме · шаблон · роли).

    Используется и для серверного рендера карточек (с подстановкой сохранённых
    значений), и как тело `<template>` для клонирования по «+ добавить».
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
        f'<input class="input" name="track_name" placeholder="напр. Backend" '
        f'value="{escape(name)}"></label>'
        + path_field(
            name="track_resume",
            label_html=f'{icon("ti-file-cv")} Резюме (путь к файлу)',
            placeholder="./resumes/backend.pdf",
            kind="resume",
            accept=".pdf,.txt,.md",
            value=resume,
        )
        + path_field(
            name="track_template",
            label_html=f'{icon("ti-mail")} Шаблон сопроводительного · пример (опц.)',
            placeholder="./cover-templates/default.pdf",
            kind="template",
            accept=".pdf,.txt,.md",
            value=template,
        )
        +
        '<label class="field"><span class="field__label">Допустимые роли (из резюме)'
        '<button type="button" class="field__gen" data-derive-roles>'
        f'{icon("ti-sparkles")} сгенерировать из резюме</button></span>'
        f'<input class="input" name="track_roles" '
        f'placeholder="загрузи резюме — роли подставятся сами" value="{escape(roles)}">'
        '<span class="field__hint" data-roles-status></span>'
        "</label>"
        "</div>"
    )


def _profile_card(tracks: list[dict] | None = None, search_map_path: str = "") -> str:
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
            value=search_map_path,
        )
        + "</div>"
    )
    if tracks:
        cards = "".join(
            track_card(
                removable=True,
                name=str(t.get("name", "")),
                resume=str(t.get("resume_path", "")),
                template=str(t.get("cover_template_path", "") or ""),
                roles=", ".join(t.get("role_gate", []) or []),
            )
            for t in tracks
        )
    else:
        cards = track_card(removable=True)
    return (
        '<section class="card">'
        f'<div class="card__title">{icon("ti-user")} Профиль</div>'
        '<div class="card__meta">Одно или несколько направлений. Каждое '
        "самодостаточно: своё резюме и шаблон.</div>"
        '<div id="tracks-list" class="tracks-grid">' + cards + "</div>"
        '<button type="button" class="btn btn--ghost" id="add-track">'
        f'{icon("ti-plus")} Добавить направление</button>'
        + search_map
        + tpl
        + "</section>"
    )


def _sources_card(
    use_aggregators: bool = True, private_handles: list[str] | None = None,
) -> str:
    agg = " checked" if use_aggregators else ""
    chip_cls = "chip chip--on" if use_aggregators else "chip"
    private_handles = private_handles or []
    if private_handles:
        chips = "".join(
            f'<span class="chip">{icon("ti-brand-telegram")} @{escape(h)}</span>'
            for h in private_handles
        )
        tg_block = (
            '<div class="field__label">Твои Telegram-каналы '
            f"(<b>{len(private_handles)}</b>) · меняются на странице "
            '<a href="/telegram">Telegram</a></div>'
            f'<div class="chip-list">{chips}</div>'
        )
    else:
        tg_block = (
            '<div class="card__meta">Каналы берём из твоего Telegram (на что подписан) '
            '— войди и выбери на странице <a href="/telegram">Telegram</a>.</div>'
        )
    return (
        '<section class="card">'
        f'<div class="card__title">{icon("ti-rss")} Источники</div>'
        + tg_block
        + '<div class="field__label">Агрегаторы</div>'
        f'<label class="chip-toggle"><input type="checkbox" name="use_aggregators"{agg}>'
        f'<span class="{chip_cls}">{icon("ti-rss")} vseti.app</span>'
        f'<span class="{chip_cls}">{icon("ti-rss")} career.habr</span></label>'
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


def _output_card(
    *, threshold: int = 70, enable_contacts: bool = False, use_embeddings: bool = True
) -> str:
    contacts = " checked" if enable_contacts else ""
    emb = " checked" if use_embeddings else ""
    return (
        '<section class="card">'
        f'<div class="card__title">{icon("ti-arrow-bar-to-down")} Выхлоп</div>'
        '<div class="card__meta">Результаты — в «Подборку» и таблицу .xlsx.</div>'
        '<label class="field"><span class="field__label">Сопроводительное — порог '
        f'<output id="threshold-val">{threshold}%</output></span>'
        '<input type="range" class="slider" name="cover_threshold" min="0" max="100" '
        f'value="{threshold}" oninput="document.getElementById(&#39;threshold-val&#39;).value='
        "this.value+&#39;%&#39;\"></label>"
        f'<label class="chip-toggle"><input type="checkbox" name="enable_contacts"{contacts}>'
        '<span class="chip">Контакт-ассист (черновик, без отправки)</span></label>'
        f'<label class="chip-toggle"><input type="checkbox" name="use_embeddings"{emb}>'
        '<span class="chip">Локальный пред-фильтр (модель ~0.22 ГБ; выкл — чисто '
        "облако, чуть больше AI-вызовов)</span></label>"
        "</section>"
    )


def _footer(backfill_days: int = 14) -> str:
    return (
        '<div class="form-footer">'
        '<label class="field" style="max-width:160px"><span class="field__label">'
        'Глубина backfill (дней)</span>'
        f'<input class="input" type="number" name="backfill_days" min="1" max="90" '
        f'value="{backfill_days}"></label>'
        '<div style="display:flex;gap:8px;align-items:flex-end">'
        '<button type="submit" name="action" value="save" class="btn">Сохранить</button>'
        '<button type="submit" name="action" value="backfill" class="btn btn--accent">'
        f'{icon("ti-player-play")} Запустить backfill</button></div>'
        "</div>"
    )


def render_settings(cfg: dict | None = None) -> str:
    """Экран 1 «Настройка» целиком (форма POST → /save), с подстановкой
    сохранённых значений из текущего `config.json` (cfg)."""
    cfg = cfg or {}
    tracks = cfg.get("tracks") or []
    search_map_path = (cfg.get("search_map") or {}).get("path", "")
    private_handles = [
        c.get("handle", "")
        for c in (cfg.get("tg_channels") or [])
        if c.get("private")
    ]
    return (
        _warning()
        + '<form method="post" action="/save">'
        + _profile_card(tracks, search_map_path)
        + _sources_card(cfg.get("use_aggregators", True), private_handles)
        + _engine_pointer()
        + _output_card(
            threshold=int(cfg.get("cover_letter_threshold", 70)),
            enable_contacts=bool(cfg.get("enable_contacts")),
            use_embeddings=bool(cfg.get("use_embeddings", True)),
        )
        + _footer(int(cfg.get("backfill_days", 14)))
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
        '<form method="post" action="/engine/save">'
        '<section class="card">'
        f'<div class="card__title">{icon("ti-cpu")} Движок AI</div>'
        f'<div class="engine-grid">{choices}</div>'
        f"{codex_panel}{ollama_panel}"
        "</section>"
        + '<div class="form-footer">'
        '<button type="submit" class="btn btn--accent">Сохранить</button></div>'
        "</form>"
    )


def render_telegram(
    *,
    has_session: bool = False,
    saved: list[str] | None = None,
    has_api_creds: bool = False,
) -> str:
    """Экран «Telegram»: свои api_id/api_hash (my.telegram.org) → телефон → код →
    2FA, затем выгрузка каналов с авто-подбором. Поток ведёт telegram.js.

    При активной сессии показываем «вход выполнен» + «Выйти», без формы.
    """
    # Блок с инструкцией и полями api_id/api_hash. Если уже заданы — свёрнут.
    creds_note = ' <span class="hint-set">заданы ✓</span>' if has_api_creds else ""
    creds = (
        f'<details class="tg-creds"{"" if not has_api_creds else ""}>'
        f'<summary>{icon("ti-key")} Telegram API: api_id и api_hash{creds_note}'
        "</summary>"
        '<div class="card__meta">Один раз получи их (бесплатно, 2 минуты): открой '
        '<a href="https://my.telegram.org" target="_blank" rel="noopener">'
        "my.telegram.org</a> → войди по своему номеру → «API development tools» → "
        "создай приложение (App title/short name — любые, например «job-agent») → "
        "скопируй <b>api_id</b> (число) и <b>api_hash</b> (строка).</div>"
        '<label class="field"><span class="field__label">api_id</span>'
        '<input class="input" name="api_id" placeholder="напр. 1234567"></label>'
        '<label class="field"><span class="field__label">api_hash</span>'
        '<input class="input" name="api_hash" type="password" '
        'placeholder="строка из my.telegram.org"></label>'
        "</details>"
    )
    if has_session:
        login = (
            '<section class="card"><div class="card__title">'
            f'{icon("ti-brand-telegram")} Telegram '
            '<span class="hint-set">вход выполнен ✓</span></div>'
            '<div class="card__meta">Аккаунт подключён — можно выгружать каналы '
            "ниже.</div>"
            '<button type="button" class="btn tg-logout">'
            f'{icon("ti-logout")} Выйти</button>'
            '<div class="login-flow__out" data-tg-login></div>'
            "</section>"
        )
    else:
        login = (
            '<section class="card"><div class="card__title">'
            f'{icon("ti-brand-telegram")} Вход в Telegram</div>'
            '<div class="card__meta">Только чтение твоих каналов. Сначала укажи свои '
            "api_id/api_hash (один раз), затем номер — Telegram пришлёт код "
            "<b>сообщением в само приложение Telegram</b> (от аккаунта «Telegram»), "
            "<b>не по SMS</b>.</div>"
            + creds
            + '<label class="field"><span class="field__label">Телефон '
            "(с кодом страны)</span>"
            '<input class="input" name="tg_phone" placeholder="+79991234567"></label>'
            '<button type="button" class="btn btn--accent tg-start">'
            f'{icon("ti-send")} Получить код</button>'
            '<div class="login-flow__out" data-tg-login></div>'
            "</section>"
        )
    saved = saved or []
    saved_block = (
        '<div class="card__meta">Сейчас в поиске (<b>'
        + str(len(saved))
        + "</b>): "
        + escape(", ".join("@" + h for h in saved))
        + "</div>"
        if saved
        else '<div class="card__meta">Пока не выбрано ни одного канала.</div>'
    )
    channels = (
        '<section class="card"><div class="card__title">'
        f'{icon("ti-list-check")} Каналы</div>'
        + saved_block
        + '<div class="card__meta">«Выгрузить каналы»: подтянем твои каналы и AI '
        "отметит те, что про вакансии. Сними/поставь галочки и сохрани.</div>"
        '<button type="button" class="btn tg-channels">'
        f'{icon("ti-refresh")} Выгрузить каналы</button>'
        '<span class="path-input__status" data-tg-channels-status></span>'
        '<div data-tg-channels-list></div>'
        '<div class="form-footer"><button type="button" '
        'class="btn btn--accent tg-save" hidden>Сохранить выбранные</button></div>'
        "</section>"
    )
    return login + channels


def render_results_screen() -> str:
    """Экран «Подборка»: фильтр по направлению + ползунок минимального совпадения
    + сетка карточек с двойными кольцами. Карточки и состояние ползунка ведёт
    results.js по /run/results (живой прогон)."""
    return (
        '<div class="res-bar">'
        '<div class="res-filters" data-res-filters></div>'
        '<a class="btn btn--accent" href="/run/output.xlsx" download>'
        f'{icon("ti-download")} Скачать .xlsx</a></div>'
        '<div class="res-slider" data-res-slider hidden>'
        f'<span class="res-slider__head">{icon("ti-map-2")}'
        "Совпадение по карте ≥</span>"
        '<input type="range" min="0" max="100" step="1" value="0" '
        'class="res-slider__range" data-res-min '
        'aria-label="минимальное совпадение по карте, %">'
        '<span class="res-slider__val mono" data-res-minval>0%</span>'
        '<span class="res-slider__count" data-res-count></span>'
        "</div>"
        '<div class="res-grid" data-res-grid></div>'
        '<div class="res-empty" data-res-empty hidden>'
        f'{icon("ti-stack-2")}<div>Пока пусто. Запусти «Подбор за период» или '
        "включи агента — финалисты появятся здесь по мере оценки.</div></div>"
    )


def render_contacts() -> str:
    """Экран «Поиск контактов»: форма по конкретной вакансии (роль+компания) →
    основная выдача (contacts) + инвестигатор. Поток ведёт contacts.js."""
    note = (
        '<div class="run-banner">'
        f'{icon("ti-info-circle")}<div>Нашёл вакансию мимо агента? Просто дай '
        "<b>ссылку</b> или загрузи <b>PDF</b> с описанием — должность и компанию "
        "определю сам, потом найду, кому написать. Отправки нет, только данные.</div></div>"
    )
    form = (
        '<section class="card"><form class="contact-form" data-contact-form>'
        '<label class="field"><span class="field__label">Ссылка на вакансию</span>'
        '<input class="input" name="link" data-contact-link '
        'placeholder="https://hh.ru/vacancy/… · career.habr.com · t.me/…"></label>'
        '<div class="contact-or"><span>или</span></div>'
        '<label class="field"><span class="field__label">PDF / текст с описанием '
        "вакансии</span>"
        '<div class="contact-file">'
        '<button type="button" class="btn" data-contact-pick>'
        f'{icon("ti-upload")} Загрузить файл</button>'
        '<input type="file" accept=".pdf,.txt,.md" data-contact-file hidden>'
        '<span class="contact-file__name" data-contact-fname></span>'
        '<input type="hidden" name="path" data-contact-path></div></label>'
        '<label class="field contact-form__check"><input type="checkbox" '
        'name="investigator"> Глубокое расследование (инвестигатор · web-обход, '
        "минуты)</label>"
        '<button type="submit" class="btn btn--accent" data-contact-go>'
        f'{icon("ti-user-search")} Найти контакты</button>'
        "</form></section>"
    )
    result = (
        '<div class="contact-status" data-contact-status hidden></div>'
        '<div class="contact-detected" data-contact-detected hidden></div>'
        '<div data-contact-result></div>'
    )
    return note + form + result


def render_agent() -> str:
    """Экран «Агент» (дашборд авто-поиска) — каркас, данные наполняет agent.js."""
    hero = (
        '<div class="hero">'
        f'<div class="hero__l"><div class="hero__icon" data-agent-hicon>{icon("ti-radar-2")}'
        "</div><div><div class=\"hero__title\" data-agent-title>Агент</div>"
        '<div class="hero__sub" data-agent-subtitle>загрузка…</div></div></div>'
        '<button type="button" class="btn btn--accent hero__toggle agent-toggle" '
        'data-agent-toggle></button></div>'
    )
    feed_card = (
        '<section class="card feed-card"><div class="feed-card__head">'
        '<span class="card__title"><span class="orb" data-agent-orb></span> '
        "Входящие · AI оценивает на лету</span>"
        '<span class="feed-rate mono" data-agent-rate></span></div>'
        '<div class="feed" data-agent-feed></div></section>'
    )
    host_card = (
        '<section class="card"><div class="host-detail__head">'
        '<span class="card__title">Хост</span>'
        '<span class="mode-chip" data-agent-hostbadge></span></div>'
        '<div class="host-detail" data-agent-hostdetail></div></section>'
    )
    pushes_card = (
        '<section class="card"><div class="pushes__head">'
        f'{icon("ti-bell-ringing")}<span class="card__title">Сильные совпадения</span>'
        '<span class="pushes__count" data-agent-pushcount>0</span></div>'
        '<div class="pushes" data-agent-pushes></div></section>'
    )
    return (
        hero
        + '<div class="stat-grid" data-agent-stats></div>'
        + '<div class="agent-cols">'
        + feed_card
        + '<div class="agent-side">' + host_card + pushes_card + "</div></div>"
    )


_PERIODS = ((1, "24 часа", "вчера и сегодня"), (3, "3 дня", "короткий хвост"),
            (7, "Неделя", "стандарт"), (30, "Месяц", "глубокий разбор"))
_STEPS = (("collect", "ti-rss", "Сбор"), ("normalize", "ti-wand", "AI читает"),
          ("filter", "ti-filter", "Фильтр"), ("score", "ti-target", "Два процента"))


def render_run(agent_interval: int = 30, days: int = 7) -> str:
    """Экран «Подбор за период»: выбор периода + живая воронка прогона.

    run.js по /run/status переключает idle ⇆ running и наполняет степпер,
    прогресс-баннер и сетку результатов (по /run/results).
    """
    banner = (
        '<div class="run-banner">'
        f'{icon("ti-bolt")}<div>Разовый прогон за выбранный период — в отличие от '
        "агента, не ждёт новых постов, а собирает всё, что вышло за период, прямо "
        "сейчас. Можно запускать, даже если агент на паузе.</div></div>"
    )
    chips = "".join(
        f'<button type="button" class="period-chip{" period-chip--on" if d == days else ""}" '
        f'data-period="{d}"><div class="period-chip__l">{escape(label)}</div>'
        f'<div class="period-chip__s">{escape(sub)}</div></button>'
        for d, label, sub in _PERIODS
    )
    idle = (
        '<div data-run-idle>'
        '<section class="card"><div class="run-idle__title">За какой период собрать</div>'
        f'<div class="period-row">{chips}</div>'
        '<div class="run-idle__foot">'
        '<span class="run-idle__meta" data-run-summary></span>'
        '<button type="button" class="btn btn--accent" data-run-start>'
        f'{icon("ti-player-play")} Запустить backfill</button></div></section>'
        '<div class="run-idle__hint">'
        f'{icon("ti-history")}<div>Выбери период и запусти — здесь развернётся живая '
        "воронка: сбор → AI читает → фильтр → два процента.</div></div></div>"
    )
    steps = "".join(
        f'<div class="step" data-step="{key}"><div class="step__circle">{icon(ic)}</div>'
        f'<div class="step__l"><div class="step__label">{escape(label)}</div>'
        f'<div class="step__sub mono" data-step-sub></div></div>'
        f'<div class="step__conn"></div></div>'
        for key, ic, label in _STEPS
    )
    active = (
        '<div data-run-active hidden>'
        f'<div class="stepper">{steps}</div>'
        '<section class="card run-progress"><div class="run-progress__icon" '
        f'data-run-picon>{icon("ti-loader")}</div>'
        '<div class="run-progress__main"><div class="run-progress__title" '
        'data-run-ptitle>Прогон…</div><div class="run-progress__sub" data-run-psub>'
        "</div></div><div class=\"run-progress__bar\"><div data-run-pbar></div></div>"
        '<div class="run-progress__pct mono" data-run-ppct></div></section>'
        '<section class="card run-feed"><div class="run-feed__head">'
        '<span class="orb orb--on"></span>'
        '<span class="card__title">Лента · что AI читает прямо сейчас</span></div>'
        '<div class="run-feed__list" data-run-feed></div></section>'
        '<div class="res-grid" data-res-grid></div></div>'
    )
    return banner + idle + active


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
