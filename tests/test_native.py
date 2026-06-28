"""Тесты нативной оболочки web-UI (Task 6.1).

Без сети и без реального окна: и сервер, и GUI-библиотека инъектируются
фейками. Проверяем оркестрацию `launch` — сервер стартует, окно создаётся на
его loopback-URL, сервер гарантированно останавливается на выходе (в т.ч. при
ошибке GUI). Плюс проброс команды `ui` из CLI.
"""

from __future__ import annotations

from typing import Any

import pytest
from webui import native


class FakeServer:
    def __init__(self, app: Any, host: str, port: int) -> None:
        self.app = app
        self.host = host
        self.port = port
        self.started = False
        self.stopped = False

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FakeWebview:
    def __init__(self, *, fail_on_start: bool = False) -> None:
        self.windows: list[tuple[str, str]] = []
        self.started = False
        self._fail_on_start = fail_on_start

    def create_window(self, title: str, url: str) -> None:
        self.windows.append((title, url))

    def start(self) -> None:
        if self._fail_on_start:
            raise RuntimeError("gui boom")
        self.started = True


def _capture_factory() -> tuple[dict[str, FakeServer], Any]:
    created: dict[str, FakeServer] = {}

    def factory(app: Any, host: str, port: int) -> FakeServer:
        server = FakeServer(app, host, port)
        created["server"] = server
        return server

    return created, factory


def test_launch_starts_server_opens_window_then_stops() -> None:
    created, factory = _capture_factory()
    gui = FakeWebview()

    native.launch(webview=gui, make_server=factory)

    server = created["server"]
    assert server.started and server.stopped
    assert gui.started
    # окно открыто на loopback-URL сервера с дефолтным заголовком
    assert gui.windows == [(native.WINDOW_TITLE, server.url)]
    assert server.host == native.DEFAULT_HOST
    assert server.port == native.DEFAULT_PORT
    assert server.url == "http://127.0.0.1:8765/"


def test_launch_passes_host_port_title_and_config(tmp_path: Any) -> None:
    created, factory = _capture_factory()
    gui = FakeWebview()
    cfg = tmp_path / "config.json"

    native.launch(
        config_path=cfg,
        host="127.0.0.1",
        port=9000,
        title="Custom",
        webview=gui,
        make_server=factory,
    )

    server = created["server"]
    assert server.port == 9000
    assert gui.windows == [("Custom", "http://127.0.0.1:9000/")]
    # create_app получил приложение (логика не переписана — это тот же app)
    assert server.app is not None


def test_launch_stops_server_even_if_gui_fails() -> None:
    created, factory = _capture_factory()
    gui = FakeWebview(fail_on_start=True)

    with pytest.raises(RuntimeError, match="gui boom"):
        native.launch(webview=gui, make_server=factory)

    # сервер всё равно остановлен (finally)
    assert created["server"].stopped


def test_launch_default_webview_is_lazy_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    created, factory = _capture_factory()
    gui = FakeWebview()
    # без явного webview берётся _import_webview (ленивый pywebview)
    monkeypatch.setattr(native, "_import_webview", lambda: gui)

    native.launch(make_server=factory)

    assert gui.started
    assert created["server"].stopped


def test_cli_ui_command_invokes_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    from job_agent.cli import main

    calls: dict[str, Any] = {}
    monkeypatch.setattr(native, "launch", lambda **kw: calls.update(kw))

    rc = main(["ui", "--port", "9001"])

    assert rc == 0
    assert calls["port"] == 9001
    assert calls["config_path"] is None
    assert calls["host"] is None
