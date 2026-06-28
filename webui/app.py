"""FastAPI-приложение web-UI.

Экран 1 «Настройка» (Task 5.1) — единственный прокручиваемый столбец max-width
720px поверх дизайн-каркаса (Task 5.0): шапка, warning про always-on, карта
«Профиль» с повторяемой карточкой направления (заменяет две фиксированные
колонки прототипа), общий блок «Карта поиска», «Источники», «Движок AI»,
«Выхлоп». Сабмит пишет `config.json`, валидный по `config.schema.json`.

Никаких внешних обращений: webfont Tabler вшит в `static/fonts/`, стили и
скрипты — локальные, CDN не используется.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from job_agent.config import ConfigError, load_config
from webui.components import chip, icon
from webui.forms import config_from_form
from webui.render import render_results, render_settings, save_result_page

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


def page(body: str, *, scripts: str = "") -> str:
    """Обёртка страницы: единственный столбец max-width 720px."""
    return (
        "<!doctype html><html lang=ru><head>"
        f"{_HEAD}</head><body><main class=col>{body}</main>{scripts}</body></html>"
    )


def create_app(config_path: Path | str | None = None) -> FastAPI:
    """Собрать FastAPI-приложение web-UI.

    `config_path` — куда писать `config.json` при сохранении формы (по умолчанию
    корень репо; в тестах подменяется на tmp).
    """
    app = FastAPI(title="Job agent web-UI")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    target = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page(render_settings(), scripts='<script src="/static/js/settings.js"></script>')

    @app.get("/results", response_class=HTMLResponse)
    def results() -> str:
        # Прогоны нигде не персистятся — пока нет данных, показываем пустое
        # состояние. Карточки собирает чистая `render_results` (юнит-тесты).
        return page(render_results([]))

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
            written = _write_and_validate(data, target)
        except ConfigError as exc:
            return HTMLResponse(page(save_result_page(ok=False, message=str(exc))), status_code=400)
        action = str(form.get("action", "save"))
        return HTMLResponse(page(save_result_page(ok=True, action=action, path=str(written))))

    return app


def _write_and_validate(data: dict, target: Path) -> Path:
    """Записать конфиг и проверить, что он грузится валидным по схеме.

    Пишем во временный файл рядом с целью, валидируем, затем атомарно подменяем —
    битый сабмит не затирает рабочий `config.json`.
    """
    import json

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        load_config(tmp)  # бросит ConfigError, если невалидно
    except ConfigError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(target)
    return target


# Экспортируемые для каркаса/тестов примитивы (совместимость с Task 5.0).
__all__ = ["create_app", "app", "page", "chip", "icon"]

app = create_app()
