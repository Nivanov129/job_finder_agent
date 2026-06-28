"""Нативная оболочка поверх web-UI (Task 6.1, опц.).

Открывает существующее FastAPI-приложение web-UI в нативном окне через
pywebview — БЕЗ переделки логики: тот же `create_app`, поднятый локальным
uvicorn на loopback, показывается в десктоп-окне. Делать имеет смысл только
поверх стабильного ядра — это тонкая обёртка, а не отдельный продукт.

Зависимость pywebview опциональна (`pip install 'job-agent[native]'`); ядро,
CLI и Docker работают headless без неё. Никаких внешних сетевых вызовов:
сервер слушает только 127.0.0.1, окно рендерит локальную страницу.

`launch()` инъектирует и сервер, и GUI-библиотеку через параметры — это
позволяет тестировать оркестрацию (старт сервера → окно → стоп сервера) на
фейках, без реального окна и без сети.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from webui.app import create_app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
WINDOW_TITLE = "Job agent"

__all__ = ["launch", "DEFAULT_HOST", "DEFAULT_PORT", "WINDOW_TITLE"]


class ServerHandle(Protocol):
    """Контракт фонового сервера web-UI для `launch`."""

    @property
    def url(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


class _UvicornServer:
    """uvicorn в фоновом потоке; слушает только loopback."""

    def __init__(self, app: Any, host: str, port: int) -> None:
        import uvicorn

        self.host = host
        self.port = port
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self, timeout: float = 10.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:  # pragma: no cover - таймингозависимо
            if time.monotonic() > deadline:
                raise RuntimeError("сервер web-UI не поднялся вовремя")
            time.sleep(0.05)

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)


def _import_webview() -> Any:
    """Лениво подтянуть pywebview с внятной ошибкой, если его нет."""
    try:
        import webview  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError(
            "Нативное окно требует pywebview: установите `pip install 'job-agent[native]'`"
        ) from exc
    return webview


def launch(
    *,
    config_path: Path | str | None = None,
    host: str | None = None,
    port: int | None = None,
    title: str = WINDOW_TITLE,
    webview: Any | None = None,
    make_server: Callable[[Any, str, int], ServerHandle] | None = None,
) -> None:
    """Открыть web-UI в нативном окне.

    Поднимает локальный сервер поверх `create_app(config_path)`, показывает его
    URL в окне и гарантированно останавливает сервер на выходе. `webview` и
    `make_server` инъектируются (по умолчанию — pywebview и uvicorn).
    """
    host = host or DEFAULT_HOST
    port = port or DEFAULT_PORT
    app = create_app(config_path)
    factory: Callable[[Any, str, int], ServerHandle] = make_server or _UvicornServer
    server = factory(app, host, port)
    server.start()
    try:
        gui = webview if webview is not None else _import_webview()
        gui.create_window(title, server.url)
        gui.start()
    finally:
        server.stop()
