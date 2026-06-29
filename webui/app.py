"""FastAPI-приложение web-UI.

Три экрана под общим меню-навигацией (`components.nav`): «Настройка» (`/`,
профиль/источники/выхлоп), «AI · авторизация» (`/engine`, выбор движка + статус
установки/авторизации Claude/Codex/Ollama + web-поиск) и «Подборка» (`/results`).
Обе формы (Настройка и AI) мержат свой поднабор полей в общий `config.json`
(валидный по `config.schema.json`); секреты авторизации движков пишутся в
`/data/.env` (`env_store`), а не в конфиг — их читают CLI-агенты из окружения.

Никаких внешних обращений: webfont Tabler вшит в `static/fonts/`, стили и
скрипты — локальные, CDN не используется.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from job_agent.config import ConfigError, load_config
from job_agent.engines import make_engine
from webui.components import chip, icon, nav
from webui.engine_status import engine_statuses, ollama_models, recommend_first
from webui.env_store import merge_env, parse_env
from webui.forms import config_from_form, engine_config_from_form
from webui.login_flow import LoginManager, LoginSpawner, default_spawner
from webui.render import (
    render_agent,
    render_contacts,
    render_engine,
    render_results_screen,
    render_run,
    render_settings,
    render_telegram,
    save_result_page,
)
from webui.runner import BackfillRunner, read_last_run
from webui.telegram_login import (
    classify_channels,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Тип загружаемого файла → подпапка в каталоге данных (рядом с config.json).
#: Имена подпапок совпадают с дефолтными плейсхолдерами полей формы.
_UPLOAD_DIRS = {
    "resume": "resumes",
    "template": "cover-templates",
    "search_map": "search-map",
    "vacancy": "vacancies-in",
}


def _fetch_url_text(url: str, *, timeout: float = 20.0) -> str:
    """Скачать страницу вакансии и грубо вытащить текст (без тегов/скриптов)."""
    import httpx

    resp = httpx.get(
        url,
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (job-agent)"},
    )
    resp.raise_for_status()
    html = resp.text
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_vacancy_text(url: str) -> str:
    """Текст вакансии по ссылке для «Поиска контактов».

    Для hh.* сначала пробуем официальный API (HTML hh — за анти-ботом/JS), иначе
    и при неудаче — обычная загрузка страницы (`_fetch_url_text`). Так hh-ссылки
    начинают работать там, где доступен `api.hh.ru`, не ломая прочие агрегаторы.
    """
    from webui.hh import fetch_hh_vacancy_text

    hh_text = fetch_hh_vacancy_text(url)
    if hh_text:
        return hh_text
    return _fetch_url_text(url)

#: Потолок размера загрузки (UI бывает открыт в LAN — без авторизации).
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _safe_filename(raw: str) -> str:
    """Безопасное имя файла: только базовое имя, без обхода путей.

    `Path(...).name` срезает любые каталоги (в т.ч. `../`). Опасные для пути и
    управляющие символы заменяются на `_`, но Unicode-буквы сохраняются —
    кириллические имена («Моё резюме.pdf») не калечатся. Пустое/служебное → `file`.
    """
    base = Path(raw or "").name
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", base).strip(". ")
    return base or "file"

#: Базовый <head>: локальные стили + локальный webfont Tabler (НЕ CDN).
_HEAD = """\
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job agent · настройка</title>
<link rel="stylesheet" href="/static/css/tabler-icons.css">
<link rel="stylesheet" href="/static/css/tokens.css">
<link rel="stylesheet" href="/static/css/components.css">
"""

#: Куда писать конфиг по умолчанию: корень репо (рядом с config.schema.json).
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"

#: Скрипты экрана «Подбор за период»: воронка (run.js) + сетка карточек (results.js).
_RUN_SCRIPTS = (
    '<script src="/static/js/run.js"></script>'
    '<script src="/static/js/results.js"></script>'
)


#: Заголовок/подзаголовок топбара по маршруту (как в прототипе).
_TITLES: dict[str, tuple[str, str]] = {
    "/agent": ("Агент", "always-on · реагирует на новые посты в реальном времени"),
    "/run": ("Подбор за период", "разовый прогон за выбранный отрезок времени"),
    "/results": ("Подборка", "финалисты с двумя процентами, по убыванию резюме %"),
    "/contacts": ("Поиск контактов", "контакты к конкретной вакансии — даже не из агента"),
    "/": ("Настройка", "направления, источники и выхлоп"),
    "/engine": ("Движок AI", "твой AI считает каждое совпадение локально"),
    "/telegram": ("Telegram", "вход в аккаунт и каналы-источники"),
}


def page(body: str, *, scripts: str = "", active: str = "") -> str:
    """Оболочка: сайдбар + топбар (заголовок экрана + чип режима) + контент."""
    from html import escape as _esc

    title, sub = _TITLES.get(active, ("Job Agent", ""))
    topbar = (
        '<header class="topbar"><div class="topbar__t">'
        f'<div class="topbar__title">{_esc(title)}</div>'
        f'<div class="topbar__sub">{_esc(sub)}</div></div>'
        '<span class="mode-chip" data-mode-chip><span class="orb" data-agent-orb>'
        "</span><span data-agent-mode>…</span></span></header>"
    )
    return (
        "<!doctype html><html lang=ru><head>"
        f"{_HEAD}</head><body><div class=app>{nav(active)}"
        f'<main class=main>{topbar}<div class="main__inner">{body}</div></main></div>'
        f'{scripts}<script src="/static/js/app.js"></script></body></html>'
    )


def create_app(
    config_path: Path | str | None = None,
    *,
    login_spawner: LoginSpawner | None = None,
    backfill_runner: BackfillRunner | None = None,
    telegram_login: object | None = None,
) -> FastAPI:
    """Собрать FastAPI-приложение web-UI.

    `config_path` — куда писать `config.json` при сохранении формы (по умолчанию
    корень репо; в тестах подменяется на tmp). `login_spawner` — порождение
    процесса входа (по умолчанию реальный Popen; в тестах — фейк).
    """
    app = FastAPI(title="Job agent web-UI")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def _no_stale_static(request: Request, call_next: Any) -> Any:
        # Статика (js/css) меняется при пересборке образа — заставляем браузер
        # всегда перепроверять (ETag даёт дешёвый 304), иначе после обновления
        # выполняется старый закешированный JS и кнопки «не работают».
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response
    target = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH

    envfile = target.parent / ".env"
    logins = LoginManager(
        envfile, spawn=login_spawner or default_spawner(envfile)
    )
    runner = backfill_runner or BackfillRunner()
    # Telethon-логин ленив (создаёт фоновый event loop) — поднимаем при первом
    # обращении; в тестах подменяется через telegram_login.
    _tg: dict[str, object] = {"login": telegram_login}

    def _tg_login() -> object:
        if _tg["login"] is None:
            from webui.telegram_login import TelegramLogin

            _tg["login"] = TelegramLogin(envfile)
        return _tg["login"]

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page(
            render_settings(_load_raw(target)),
            scripts='<script src="/static/js/settings.js"></script>',
            active="/",
        )

    @app.get("/agent", response_class=HTMLResponse)
    def agent_page() -> str:
        return page(
            render_agent(),
            scripts='<script src="/static/js/agent.js"></script>',
            active="/agent",
        )

    @app.get("/results", response_class=HTMLResponse)
    def results() -> str:
        # Карточки строит results.js по /run/results (живые результаты прогона).
        return page(
            render_results_screen(),
            scripts='<script src="/static/js/results.js"></script>',
            active="/results",
        )

    @app.get("/contacts", response_class=HTMLResponse)
    def contacts_page() -> str:
        return page(
            render_contacts(),
            scripts='<script src="/static/js/contacts.js"></script>',
            active="/contacts",
        )

    @app.post("/contacts/search")
    async def contacts_search(request: Request) -> JSONResponse:
        # Супер-простой вход: ссылка ИЛИ PDF с вакансией. Должность и компанию
        # достаём сами (нормализация движком), затем — контакты + опц. инвестигатор.
        from job_agent.enrich.contacts import find_contacts
        from job_agent.enrich.investigator import investigate_contacts
        from job_agent.models import RawPost, Vacancy
        from job_agent.normalize import normalize_post
        from job_agent.pipeline import _read_document
        from job_agent.websearch import make_searcher

        form = await request.form()
        link = str(form.get("link", "")).strip()
        path = str(form.get("path", "")).strip()
        role = str(form.get("role", "")).strip()
        company = str(form.get("company", "")).strip()
        want_inv = str(form.get("investigator", "")).lower() in ("on", "true", "1")
        # Кнопка «Контакт» в карточке подборки уже знает должность+компанию —
        # тогда не тянем/не нормализуем, ищем сразу по ним.
        direct = bool(role and company)
        if not link and not path and not direct:
            return JSONResponse(
                {"error": "дай ссылку на вакансию или загрузи PDF"}, status_code=400
            )
        os.environ.update(parse_env(envfile))  # ключи из .env видны движку
        cfg = load_config(target)
        engine = make_engine(cfg)
        base = target.parent

        def _run() -> dict[str, Any]:
            if direct:
                vac = Vacancy(
                    title=role, company=company,
                    link_or_contact=link or None, url=link or None,
                )
            else:
                # 1) текст вакансии: из PDF/файла или со страницы по ссылке
                try:
                    if path:
                        text = _read_document(path, base)
                    else:
                        text = _fetch_vacancy_text(link)
                except Exception as exc:
                    return {"error": f"не прочитать вакансию: {str(exc)[:160]}"}
                if not text.strip():
                    return {
                        "error": "пусто — со страницы не вытащить текст. Для hh.ru "
                        "сохрани вакансию в PDF или впиши роль и компанию вручную."
                    }
                # 2) достаём должность+компанию нормализацией
                post = RawPost(raw_text=text[:8000], source="manual", url=link or None)
                vacs = normalize_post(post, engine, output_lang=cfg.output_lang)
                if not vacs:
                    return {"error": "не распознал вакансию в тексте"}
                vac = vacs[0]
                if link and not vac.url:
                    vac = vac.model_copy(update={"url": link})
            out: dict[str, Any] = {
                "detected": {"role": vac.title, "company": vac.company or ""},
                "contacts": None,
                "investigation": None,
            }
            if not (vac.company or "").strip():
                out["warning"] = "компанию не нашёл — контакты ищу по названию"
            # 3) контакты
            try:
                res = find_contacts(
                    vac, engine, make_searcher(cfg), track_name=vac.title,
                    enable_contacts=True, output_lang=cfg.output_lang,
                )
                out["contacts"] = res.model_dump() if res is not None else None
            except Exception as exc:
                out["contacts_error"] = str(exc)[:200]
            if want_inv:
                try:
                    inv = investigate_contacts(
                        vac, engine, track_name=vac.title,
                        enable_investigator=True, output_lang=cfg.output_lang,
                    )
                    out["investigation"] = inv.model_dump() if inv is not None else None
                except Exception as exc:
                    out["investigation_error"] = str(exc)[:200]
            return out

        result = await run_in_threadpool(_run)
        status = 400 if "error" in result else 200
        return JSONResponse(result, status_code=status)

    @app.get("/engine", response_class=HTMLResponse)
    def engine() -> str:
        cfg = _load_raw(target)
        env = {**os.environ, **parse_env(envfile)}
        se = cfg.get("scoring_engine", "cli")
        return page(
            render_engine(
                scoring_engine=se,
                cli_tool=cfg.get("cli_tool", "codex"),
                has_ollama_key=bool(env.get("OLLAMA_API_KEY")),
                has_openrouter_key=bool(env.get("OPENROUTER_API_KEY")),
            ),
            scripts='<script src="/static/js/engine.js"></script>',
            active="/engine",
        )

    @app.post("/engine/ollama/models")
    async def engine_ollama_models(request: Request) -> JSONResponse:
        # Список моделей Ollama Cloud для дропдауна — рекомендованные под задачу
        # первыми. Ключ берём из формы (вставленный, ещё не сохранённый) или из
        # .env. Недоступность/неверный ключ → пустой список.
        form = await request.form()
        env = {**os.environ, **parse_env(envfile)}
        key = str(form.get("key", "")).strip() or env.get("OLLAMA_API_KEY")
        models = await run_in_threadpool(ollama_models, "", api_key=key)
        # Сокращаем дропдаун: рекомендованные под задачу первыми, не больше 12.
        return JSONResponse({"models": recommend_first(models)[:12]})

    @app.get("/engine/status")
    def engine_status() -> JSONResponse:
        cfg = _load_raw(target)
        env = {**os.environ, **parse_env(envfile)}
        ollama_url = cfg.get("api_base_url", "") if cfg.get("scoring_engine") == "ollama" else ""
        statuses = engine_statuses(env=env, ollama_url=ollama_url)
        return JSONResponse({"engines": [s.as_dict() for s in statuses]})

    @app.post("/engine/login/start")
    async def engine_login_start(request: Request) -> JSONResponse:
        # Сервер сам запускает claude setup-token / codex login и отдаёт ссылку.
        # Блокирующий запуск+чтение — в threadpool, чтобы не морозить event loop
        # (иначе на время входа зависает весь UI).
        form = await request.form()
        res = await run_in_threadpool(logins.start, str(form.get("engine", "")))
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/engine/login/submit")
    async def engine_login_submit(request: Request) -> JSONResponse:
        # Завершить вход: claude — код → токен в .env; codex — ждём подтверждения
        # в браузере. Долгое ожидание — в threadpool (UI остаётся отзывчивым).
        form = await request.form()
        res = await run_in_threadpool(
            logins.submit, str(form.get("engine", "")), str(form.get("code", ""))
        )
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/engine/test")
    async def engine_test(request: Request) -> JSONResponse:
        # Реальная проба движка (subprocess/сеть) — в threadpool, не в event loop.
        form = await request.form()
        ok, message = await run_in_threadpool(
            _probe_engine, str(form.get("engine", "")), _load_raw(target), envfile
        )
        return JSONResponse({"ok": ok, "message": message}, status_code=200 if ok else 400)

    @app.post("/engine/save", response_class=HTMLResponse)
    async def engine_save(request: Request) -> HTMLResponse:
        form = await request.form()
        updates, secrets = engine_config_from_form(form)
        try:
            _merge_and_validate(updates, target)
        except ConfigError as exc:
            return HTMLResponse(
                page(save_result_page(ok=False, message=str(exc)), active="/engine"),
                status_code=400,
            )
        note_html = ""
        if secrets:  # токены/ключи — в .env, не в config.json
            merge_env(envfile, secrets)
            # Web-UI перечитывает .env на каждый запрос (кнопка «Проверить» уже
            # с новым ключом), но пайплайн-контейнер берёт env при старте — для
            # ночного прогона нужен перезапуск стека.
            note_html = (
                "Кнопка «Проверить» уже использует новый ключ. Ночной прогон "
                "подхватит его после перезапуска стека: "
                "<code>docker compose up -d</code>."
            )
        verify_engine = str(form.get("engine", "")) or "codex"
        return HTMLResponse(
            page(
                save_result_page(
                    ok=True,
                    path=str(target),
                    note_html=note_html,
                    back_href="/engine",
                    back_label="вернуться к движку",
                    verify_engine=verify_engine,
                ),
                active="/engine",
                scripts='<script src="/static/js/engine.js"></script>',
            )
        )

    @app.post("/upload")
    async def upload(file: UploadFile = File(...), kind: str = Form(...)) -> JSONResponse:
        # Кнопка «Загрузить» рядом с полем-путём кладёт файл в каталог данных и
        # возвращает относительный путь, который JS подставляет в поле. Путь
        # резолвится пайплайном относительно base_dir (= каталог config.json).
        subdir = _UPLOAD_DIRS.get(kind)
        if subdir is None:
            return JSONResponse({"error": f"неизвестный тип файла: {kind}"}, status_code=400)
        content = await file.read()
        if len(content) > _MAX_UPLOAD_BYTES:
            return JSONResponse(
                {"error": f"файл больше {_MAX_UPLOAD_BYTES // (1024 * 1024)} МБ"},
                status_code=413,
            )
        name = _safe_filename(file.filename or "")
        dest_dir = target.parent / "uploads" / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / name).write_bytes(content)
        return JSONResponse({"path": f"uploads/{subdir}/{name}", "name": name})

    @app.post("/roles/derive")
    async def roles_derive(request: Request) -> JSONResponse:
        # «Допустимые роли» (role_gate) генерим из резюме тем же движком, что и
        # подбор: AI достаёт базовые названия должностей. Эти роли — гейт включения
        # вакансий в подборку (по названию должности), уже в языке резюме.
        from job_agent.pipeline import _read_document
        from job_agent.titlefilter import derive_titles

        form = await request.form()
        path = str(form.get("path", "")).strip()
        if not path:
            return JSONResponse({"error": "не указан путь к резюме"}, status_code=400)
        base = target.parent
        try:
            text = await run_in_threadpool(_read_document, path, base)
        except Exception as exc:  # файл не найден / нечитаем
            return JSONResponse(
                {"error": f"резюме не прочитать: {str(exc)[:160]}"}, status_code=400
            )
        if not text.strip():
            return JSONResponse({"error": "резюме пустое"}, status_code=400)
        try:
            os.environ.update(parse_env(envfile))  # ключи из .env видны движку
            engine = make_engine(load_config(target))
            roles = await run_in_threadpool(derive_titles, engine, text)
        except Exception as exc:  # движок не авторизован / упал
            return JSONResponse(
                {"error": f"движок недоступен: {str(exc)[:160]}"}, status_code=502
            )
        return JSONResponse({"roles": roles})

    @app.post("/save", response_class=HTMLResponse)
    async def save(request: Request) -> HTMLResponse:
        form = await request.form()
        data = config_from_form(form)
        # Сохранить приватные каналы из Telegram (их форма Настройки не несёт),
        # чтобы сохранение Настройки их не затирало.
        existing_private = [
            c for c in _load_raw(target).get("tg_channels", []) if c.get("private")
        ]
        data["tg_channels"] = data.get("tg_channels", []) + existing_private
        try:
            # Мерж: Настройка не несёт полей движка — берём их из текущего
            # конфига; при первом сохранении проставляем дефолтный движок.
            written = _merge_and_validate(
                data, target, defaults={"scoring_engine": "cli", "cli_tool": "codex"}
            )
        except ConfigError as exc:
            return HTMLResponse(
                page(save_result_page(ok=False, message=str(exc)), active="/"),
                status_code=400,
            )
        action = str(form.get("action", "save"))
        if action == "backfill":
            # Конфиг сохранён — запускаем фоновый прогон и ведём на «Подбор за период».
            runner.start(target)
            cfg = _load_raw(target)
            return HTMLResponse(
                page(
                    render_run(
                        int(cfg.get("agent_interval_minutes", 30)),
                        int(cfg.get("backfill_days", 7)),
                    ),
                    scripts=_RUN_SCRIPTS,
                    active="/run",
                )
            )
        return HTMLResponse(
            page(save_result_page(ok=True, action=action, path=str(written)), active="/")
        )

    @app.get("/telegram", response_class=HTMLResponse)
    def telegram_page() -> str:
        env = {**os.environ, **parse_env(envfile)}
        cfg = _load_raw(target)
        saved = [
            c.get("handle", "")
            for c in cfg.get("tg_channels", [])
            if c.get("private")
        ]
        return page(
            render_telegram(
                has_session=bool(env.get("TELEGRAM_SESSION")),
                saved=saved,
                has_api_creds=bool(
                    env.get("TELEGRAM_API_ID") and env.get("TELEGRAM_API_HASH")
                ),
                has_bot_token=bool(env.get("TELEGRAM_BOT_TOKEN")),
                owner_chat_id=cfg.get("owner_chat_id"),
            ),
            scripts=(
                '<script src="/static/js/telegram.js?v=qr1"></script>'
                '<script src="/static/js/bot.js"></script>'
            ),
            active="/telegram",
        )

    @app.post("/telegram/bot/connect")
    async def telegram_bot_connect(request: Request) -> JSONResponse:
        # Подключить бот-уведомления: токен (от @BotFather) → .env, затем ловим
        # chat_id владельца через getUpdates (он должен был нажать Start у бота).
        from webui.bot_connect import BOT_TOKEN_ENV, resolve_owner_chat_id

        form = await request.form()
        token = str(form.get("bot_token", "")).strip()
        if token:
            merge_env(envfile, {BOT_TOKEN_ENV: token})
        os.environ.update(parse_env(envfile))
        token = os.environ.get(BOT_TOKEN_ENV, "")
        if not token:
            return JSONResponse(
                {"ok": False, "error": "вставь токен бота от @BotFather"}, status_code=400
            )
        chat_id = await run_in_threadpool(resolve_owner_chat_id, token)
        if chat_id is None:
            return JSONResponse(
                {"ok": False, "error": "не вижу сообщений боту. Открой своего бота в "
                 "Telegram, нажми Start (или напиши /start), затем «Подключить» снова."},
                status_code=400,
            )
        _merge_and_validate({"owner_chat_id": chat_id}, target)
        return JSONResponse({"ok": True, "chat_id": chat_id})

    @app.post("/telegram/bot/test")
    async def telegram_bot_test(request: Request) -> JSONResponse:
        # Отправить тест-сообщение в личный чат владельца (проверка связи).
        from webui.bot_connect import BOT_TOKEN_ENV, send_test_message

        os.environ.update(parse_env(envfile))
        token = os.environ.get(BOT_TOKEN_ENV, "")
        chat_id = _load_raw(target).get("owner_chat_id")
        if not token or not chat_id:
            return JSONResponse(
                {"ok": False, "error": "сначала подключи бота"}, status_code=400
            )
        ok = await run_in_threadpool(
            send_test_message, token, chat_id,
            "Job Agent на связи ✅ Сюда буду присылать новые вакансии, пока агент работает.",
        )
        return JSONResponse({"ok": ok}, status_code=200 if ok else 502)

    def _resolve_tg_creds(form: Any) -> tuple[str, str]:
        """api_id/api_hash из формы (если введены) либо из .env; введённые
        запоминаем в .env, чтобы не вводить заново. Возвращает ('','') если нет."""
        env = {**os.environ, **parse_env(envfile)}
        api_id = str(form.get("api_id", "")).strip() or env.get("TELEGRAM_API_ID", "")
        api_hash = (
            str(form.get("api_hash", "")).strip() or env.get("TELEGRAM_API_HASH", "")
        )
        if str(form.get("api_id", "")).strip() or str(form.get("api_hash", "")).strip():
            merge_env(envfile, {"TELEGRAM_API_ID": api_id, "TELEGRAM_API_HASH": api_hash})
        return api_id, api_hash

    @app.post("/telegram/login/start")
    async def telegram_start(request: Request) -> JSONResponse:
        form = await request.form()
        api_id, api_hash = _resolve_tg_creds(form)
        if not (api_id and api_hash):
            return JSONResponse(
                {"ok": False, "message": "сначала укажи api_id и api_hash "
                 "(my.telegram.org → API development tools)"},
                status_code=400,
            )
        res = await run_in_threadpool(
            _tg_login().start, api_id, api_hash, str(form.get("phone", "")),
        )
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/telegram/login/qr")
    async def telegram_qr_start(request: Request) -> JSONResponse:
        form = await request.form()
        api_id, api_hash = _resolve_tg_creds(form)
        if not (api_id and api_hash):
            return JSONResponse(
                {"ok": False, "message": "сначала укажи api_id и api_hash "
                 "(my.telegram.org → API development tools)"},
                status_code=400,
            )
        res = await run_in_threadpool(_tg_login().qr_start, api_id, api_hash)
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/telegram/login/qr/poll")
    async def telegram_qr_poll() -> JSONResponse:
        res = await run_in_threadpool(_tg_login().qr_poll)
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/telegram/login/session")
    async def telegram_session(request: Request) -> JSONResponse:
        form = await request.form()
        api_id, api_hash = _resolve_tg_creds(form)
        res = await run_in_threadpool(
            _tg_login().import_session,
            api_id,
            api_hash,
            str(form.get("session", "")),
        )
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/telegram/logout")
    async def telegram_logout() -> JSONResponse:
        # Выход: убрать сессию и из .env, И из os.environ процесса (она там с
        # запуска контейнера через env_file) — иначе страница думает, что вошли.
        merge_env(envfile, {"TELEGRAM_SESSION": None})
        os.environ.pop("TELEGRAM_SESSION", None)
        return JSONResponse({"ok": True})

    @app.post("/telegram/login/code")
    async def telegram_code(request: Request) -> JSONResponse:
        form = await request.form()
        res = await run_in_threadpool(_tg_login().submit_code, str(form.get("code", "")))
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/telegram/login/password")
    async def telegram_password(request: Request) -> JSONResponse:
        form = await request.form()
        res = await run_in_threadpool(
            _tg_login().submit_password, str(form.get("password", ""))
        )
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/telegram/channels")
    async def telegram_channels() -> JSONResponse:
        # Выгрузить каналы по сессии из .env и пометить «про вакансии» (AI).
        env = {**os.environ, **parse_env(envfile)}
        channels = await run_in_threadpool(
            _tg_login().list_channels,
            env.get("TELEGRAM_API_ID", ""),
            env.get("TELEGRAM_API_HASH", ""),
            env.get("TELEGRAM_SESSION", ""),
        )
        if not channels:
            return JSONResponse({"channels": [], "message": "каналы не получены — войдите"})
        job_ids: set[str] = set()
        try:  # классификация опциональна — без движка просто без авто-отметки
            os.environ.update(parse_env(envfile))  # ключи из .env видны движку
            engine = make_engine(load_config(target))
            job_ids = await run_in_threadpool(classify_channels, engine, channels)
        except Exception:
            job_ids = set()
        out = [{**c, "job": str(c["id"]) in job_ids} for c in channels]
        # Сначала каналы с вакансиями (галочка), потом остальные.
        out.sort(key=lambda c: (not c["job"], str(c.get("title", "")).lower()))
        return JSONResponse({"channels": out, "job_count": len(job_ids)})

    @app.post("/telegram/save", response_class=HTMLResponse)
    async def telegram_save(request: Request) -> HTMLResponse:
        form = await request.form()
        handles = [h for h in form.getlist("channel") if str(h).strip()]
        # Сохранить публичные каналы из Настройки, чтобы не затереть их.
        existing_public = [
            c for c in _load_raw(target).get("tg_channels", []) if not c.get("private")
        ]
        updates = {
            "tg_channels": [{"handle": str(h), "private": True} for h in handles]
            + existing_public
        }
        try:
            _merge_and_validate(updates, target)
        except ConfigError as exc:
            return HTMLResponse(
                page(save_result_page(ok=False, message=str(exc)), active="/telegram"),
                status_code=400,
            )
        return HTMLResponse(
            page(
                save_result_page(
                    ok=True,
                    path=str(target),
                    note_html=f"Каналов сохранено: {len(handles)} (приватный сбор).",
                    back_href="/telegram",
                    back_label="вернуться в Telegram",
                ),
                active="/telegram",
            )
        )

    @app.get("/run", response_class=HTMLResponse)
    def run_page() -> str:
        cfg = _load_raw(target)
        return page(
            render_run(
                int(cfg.get("agent_interval_minutes", 30)),
                int(cfg.get("backfill_days", 7)),
            ),
            scripts=_RUN_SCRIPTS,
            active="/run",
        )

    @app.get("/run/status")
    def run_status() -> JSONResponse:
        return JSONResponse(runner.state())

    @app.get("/run/results")
    def run_results() -> JSONResponse:
        # Результаты текущего/последнего прогона (наполняются по мере скоринга).
        return JSONResponse({"results": runner.results()})

    @app.post("/run/start")
    async def run_start(request: Request) -> JSONResponse:
        # «Подбор за период»: сохранить глубину в днях и запустить разовый прогон.
        form = await request.form()
        try:
            days = max(1, min(90, int(str(form.get("days", "")) or 7)))
        except ValueError:
            days = 7
        try:
            _merge_and_validate({"backfill_days": days}, target)
        except ConfigError:
            pass
        ok = runner.start(target)
        return JSONResponse({"ok": ok, "days": days, "running": runner.is_running()})

    @app.post("/agent/start")
    async def agent_start(request: Request) -> JSONResponse:
        form = await request.form()
        cfg = _load_raw(target)
        try:
            interval = int(
                str(form.get("interval", "")) or cfg.get("agent_interval_minutes", 30)
            )
        except ValueError:
            interval = 30
        interval = max(5, min(1440, interval))
        try:  # запомнить интервал в конфиг
            _merge_and_validate({"agent_interval_minutes": interval}, target)
        except ConfigError:
            pass
        runner.start_agent(target, interval)
        return JSONResponse({"ok": True, "interval_min": interval})

    @app.post("/agent/stop")
    def agent_stop() -> JSONResponse:
        runner.stop_agent()
        return JSONResponse({"ok": True})

    @app.get("/agent/status")
    def agent_status() -> JSONResponse:
        st = runner.agent_status()
        last = read_last_run(target.parent / "last_run.json")
        st["last_run"] = last.isoformat() if last else ""
        return JSONResponse(st)

    @app.get("/run/output.xlsx")
    def run_output() -> Response:
        out = target.parent / "backfill.xlsx"
        if not out.exists():
            return JSONResponse({"error": "файл прогона не найден"}, status_code=404)
        return FileResponse(
            out,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="backfill.xlsx",
        )

    return app


def _load_raw(target: Path) -> dict:
    """Текущий config.json как dict (или `{}`, если нет/битый) — для мержа/префилла."""
    if target.exists():
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def _merge_and_validate(updates: dict, target: Path, *, defaults: dict | None = None) -> Path:
    """Слить `updates` в текущий конфиг, проверить по схеме, атомарно записать.

    Две страницы (Настройка и AI) пишут один `config.json`, каждая — свой поднабор
    полей. `defaults` заполняют недостающие обязательные поля при первом сохранении.
    Битый сабмит не затирает рабочий конфиг (валидация на temp до подмены).
    """
    merged = {**_load_raw(target), **updates}
    for key, value in (defaults or {}).items():
        merged.setdefault(key, value)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        load_config(tmp)  # бросит ConfigError, если невалидно
    except ConfigError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(target)
    return target


def _probe_engine(engine_key: str, cfg: dict, envfile: Path) -> tuple[bool, str]:
    """Реальная мини-проба движка для кнопки «Проверить» (явное действие).

    Движок строится напрямую (без полного Config — треки не нужны). Для CLI в
    subprocess инжектится окружение из `.env`, чтобы только что вставленный токен
    проверялся сразу (пайплайн подхватит его после рестарта стека).
    """
    import subprocess

    prompt = "Ответь одним словом: ok"
    try:
        if engine_key in ("claude", "codex"):
            from job_agent.engines.cli import CliEngine

            env = {**os.environ, **parse_env(envfile)}

            def runner(argv: list[str]) -> str:
                return subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env,
                    check=True,
                    stdin=subprocess.DEVNULL,  # codex иначе ждёт ввод из stdin
                ).stdout

            out = CliEngine(engine_key, runner=runner).complete(prompt)
        elif engine_key == "ollama":
            from job_agent.engines.ollama import OllamaEngine

            env = {**os.environ, **parse_env(envfile)}
            out = OllamaEngine(
                cfg.get("ollama_model") or "",
                base_url=cfg.get("api_base_url"),
                api_key=env.get("OLLAMA_API_KEY"),  # свежий ключ из .env сразу
            ).complete(prompt)
        elif engine_key == "api_key":
            from job_agent.engines.api_key import ApiKeyEngine

            out = ApiKeyEngine(
                cfg.get("api_key") or "", base_url=cfg.get("api_base_url")
            ).complete(prompt)
        elif engine_key == "openrouter":
            from job_agent.engines.api_key import ApiKeyEngine

            env = {**os.environ, **parse_env(envfile)}
            out = ApiKeyEngine(
                env.get("OPENROUTER_API_KEY") or "",  # свежий ключ из .env сразу
                provider="openrouter",
            ).complete(prompt)
        else:
            return False, f"неизвестный движок: {engine_key}"
        text = (out or "").strip()
        return True, text[:120] or "пустой ответ"
    except Exception as exc:  # сеть/процесс/конфиг — показываем причину
        return False, str(exc)[:200]


# Экспортируемые для каркаса/тестов примитивы (совместимость с Task 5.0).
__all__ = ["create_app", "app", "page", "chip", "icon"]

app = create_app()
