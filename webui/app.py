"""FastAPI-приложение web-UI (дизайн-каркас, Task 5.0).

Отдаёт статику локально (`/static`) и базовую страницу-каркас, демонстрирующую
токены и общие компоненты. Экраны «Настройка» (Task 5.1) и «Подборка» (Task 5.2)
строятся поверх этого каркаса. Никаких внешних обращений: webfont Tabler вшит в
`static/fonts/`, стили — локальные, CDN не используется.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from webui.components import badge, card, chip, icon

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Базовый <head>: локальные стили + локальный webfont Tabler (НЕ CDN).
_HEAD = """\
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job agent</title>
<link rel="stylesheet" href="/static/css/tabler-icons.css">
<link rel="stylesheet" href="/static/css/tokens.css">
<link rel="stylesheet" href="/static/css/components.css">
"""


def _page(title: str, body: str) -> str:
    """Обёртка страницы: единственный столбец max-width 720px."""
    return (
        "<!doctype html><html lang=ru><head>"
        f"{_HEAD}</head><body><main class=col>{body}</main></body></html>"
    )


def _scaffold_body() -> str:
    """Демонстрация каркаса: шапка, warning-плашка, карточка с компонентами."""
    header = (
        '<div class="app-header">'
        f'<span class="app-header__icon">{icon("ti-radar-2")}</span>'
        "<div><div class=\"card__title\">Job agent · каркас</div>"
        '<div class="card__meta">локально на вашем компьютере</div></div>'
        "</div>"
    )
    warning = (
        '<div class="notice-warning">'
        f"{icon('ti-alert-triangle')} Ночной мониторинг требует включённого хоста (always-on)."
        "</div>"
    )
    demo = card(
        title="Демонстрация компонентов",
        meta="бейдж · чип · карточка — из общего слоя",
        right=badge(86),
        body=(
            f'<div style="display:flex;gap:8px;flex-wrap:wrap">'
            f'{chip("vseti.app", on=True, icon_name="ti-rss")}'
            f'{chip("getmatch")}'
            f'{chip("Таблица .xlsx", icon_name="ti-arrow-bar-to-down")}'
            f"</div>"
        ),
    )
    return header + warning + demo


def create_app() -> FastAPI:
    """Собрать FastAPI-приложение каркаса."""
    app = FastAPI(title="Job agent web-UI")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _page("Job agent", _scaffold_body())

    return app


app = create_app()
