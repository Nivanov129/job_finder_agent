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

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from job_agent.config import ConfigError, load_config
from webui.components import chip, icon, nav
from webui.engine_status import engine_statuses, ollama_models, recommend_first
from webui.env_store import merge_env, parse_env
from webui.forms import config_from_form, engine_config_from_form
from webui.login_flow import LoginManager, LoginSpawner, default_spawner
from webui.render import render_engine, render_results, render_settings, save_result_page

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Тип загружаемого файла → подпапка в каталоге данных (рядом с config.json).
#: Имена подпапок совпадают с дефолтными плейсхолдерами полей формы.
_UPLOAD_DIRS = {
    "resume": "resumes",
    "template": "cover-templates",
    "search_map": "search-map",
}

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


def page(body: str, *, scripts: str = "", active: str = "") -> str:
    """Обёртка страницы: верхнее меню + единственный столбец max-width 720px.

    `active` — текущий маршрут для подсветки пункта меню.
    """
    return (
        "<!doctype html><html lang=ru><head>"
        f"{_HEAD}</head><body>{nav(active)}"
        f"<main class=col>{body}</main>{scripts}</body></html>"
    )


def create_app(
    config_path: Path | str | None = None,
    *,
    login_spawner: LoginSpawner | None = None,
) -> FastAPI:
    """Собрать FastAPI-приложение web-UI.

    `config_path` — куда писать `config.json` при сохранении формы (по умолчанию
    корень репо; в тестах подменяется на tmp). `login_spawner` — порождение
    процесса входа (по умолчанию реальный Popen; в тестах — фейк).
    """
    app = FastAPI(title="Job agent web-UI")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    target = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH

    envfile = target.parent / ".env"
    logins = LoginManager(
        envfile, spawn=login_spawner or default_spawner(envfile)
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page(
            render_settings(),
            scripts='<script src="/static/js/settings.js"></script>',
            active="/",
        )

    @app.get("/results", response_class=HTMLResponse)
    def results() -> str:
        # Прогоны нигде не персистятся — пока нет данных, показываем пустое
        # состояние. Карточки собирает чистая `render_results` (юнит-тесты).
        return page(render_results([]), active="/results")

    @app.get("/engine", response_class=HTMLResponse)
    def engine() -> str:
        cfg = _load_raw(target)
        env = {**os.environ, **parse_env(envfile)}
        se = cfg.get("scoring_engine", "cli")
        return page(
            render_engine(
                scoring_engine=se,
                cli_tool=cfg.get("cli_tool", "codex"),
                ollama_model=cfg.get("ollama_model", ""),
                web_search_url=(cfg.get("web_search") or {}).get("url", ""),
                has_ollama_key=bool(env.get("OLLAMA_API_KEY")),
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
        return JSONResponse({"models": recommend_first(models)})

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

    @app.post("/save", response_class=HTMLResponse)
    async def save(request: Request) -> HTMLResponse:
        form = await request.form()
        data = config_from_form(form)
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
        return HTMLResponse(
            page(save_result_page(ok=True, action=action, path=str(written)), active="/")
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
                    argv, capture_output=True, text=True, timeout=60, env=env, check=True
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
        else:
            return False, f"неизвестный движок: {engine_key}"
        text = (out or "").strip()
        return True, text[:120] or "пустой ответ"
    except Exception as exc:  # сеть/процесс/конфиг — показываем причину
        return False, str(exc)[:200]


# Экспортируемые для каркаса/тестов примитивы (совместимость с Task 5.0).
__all__ = ["create_app", "app", "page", "chip", "icon"]

app = create_app()
