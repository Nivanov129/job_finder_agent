"""Server-driven вход для CLI-движков (claude/codex): сервер сам запускает
команду авторизации, а web-UI показывает ссылку для входа и форму для кода.

Поток (claude `setup-token`): процесс печатает OAuth-ссылку → её показываем в
UI; пользователь авторизуется в браузере, получает код → вводит в форму → код
уходит в stdin процесса → процесс печатает долгоживущий токен → пишем его в
`.env` (`CLAUDE_CODE_OAUTH_TOKEN`). Поток (codex `login`): процесс печатает
ссылку → вход завершается callback'ом в браузере; «Проверить вход» дожидается
успешного выхода процесса (codex сам пишет auth.json в смонтированный каталог).

Внешняя граница — порождение процесса (`LoginSpawner`) — инъектируется: юнит-тесты
гоняют фейк-процесс, в реальную сеть/CLI не ходят. Секреты (токен) не логируются.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .env_store import merge_env

__all__ = [
    "LoginManager",
    "LoginProcess",
    "LoginSpawner",
    "LoginResult",
    "LOGIN_ENGINES",
    "URL_RE",
    "CLAUDE_TOKEN_RE",
    "DEVICE_CODE_RE",
    "default_spawner",
    "LOGIN_ARGV",
]

# Команда входа на движок. codex — device-auth: без localhost-callback, годится
# для headless/контейнера (обычный `codex login` шлёт callback на localhost,
# недостижимый из браузера пользователя).
LOGIN_ARGV: dict[str, list[str]] = {
    "claude": ["claude", "setup-token"],
    "codex": ["codex", "login", "--device-auth"],
}

# Режим входа на движок:
#  code   — claude setup-token: пользователь получает код в браузере → вводит в
#           нашу форму → код уходит в stdin → ловим токен в stdout.
#  device — codex login --device-auth: показываем ссылку + одноразовый код,
#           пользователь вводит код в браузере, CLI сам опрашивает и завершается
#           (без localhost-callback — работает headless/из контейнера).
LOGIN_ENGINES: dict[str, str] = {"claude": "code", "codex": "device"}
# Куда кладётся пойманный токен (codex токен не печатает — пишет auth.json сам).
_TOKEN_ENV_KEY: dict[str, str] = {"claude": "CLAUDE_CODE_OAUTH_TOKEN"}

URL_RE = re.compile(r"https?://[^\s'\"<>]+")
CLAUDE_TOKEN_RE = re.compile(r"sk-ant-oat[0-9A-Za-z_-]+")
# Признак неудачного обмена кода (claude печатает это и ждёт «Press Enter to
# retry», не завершаясь) — чтобы не висеть в ожидании токена 180с.
LOGIN_ERROR_RE = re.compile(r"OAuth error|Press Enter to retry|status code [45]\d\d", re.I)
# Одноразовый device-код codex, напр. «CVBJ-2XUDK».
DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4,6}-[A-Z0-9]{4,6}\b")


@dataclass
class LoginResult:
    """Итог входа: успех/ошибка, сообщение и (для claude) пойманный токен."""

    ok: bool
    message: str
    token: str | None = None


class LoginProcess(Protocol):
    """Интерфейс запущенного процесса входа (реальный Popen или фейк в тестах)."""

    def read(self, pattern: re.Pattern[str], timeout: float) -> str | None:
        """Дождаться совпадения `pattern` в выводе (ссылка/код) или None по таймауту."""
        ...

    def submit_code(self, code: str) -> None:
        """Передать код в stdin процесса (для режима 'code')."""
        ...

    def result(self, timeout: float) -> LoginResult:
        """Дождаться итога: токен (claude) или успешный выход (codex)."""
        ...

    def stop(self) -> None:
        """Завершить процесс (идемпотентно)."""
        ...


# engine -> процесс входа.
LoginSpawner = Callable[[str], LoginProcess]


class LoginManager:
    """Хранит активные сессии входа и сшивает их с записью токена в `.env`.

    Локальный однопользовательский UI — по одной активной сессии на движок.
    """

    def __init__(
        self,
        envfile: Path | str,
        *,
        spawn: LoginSpawner,
        url_timeout: float = 30.0,
        result_timeout: float = 180.0,
    ) -> None:
        self._envfile = Path(envfile)
        self._spawn = spawn
        self._url_timeout = url_timeout
        self._result_timeout = result_timeout
        self._active: dict[str, LoginProcess] = {}

    def start(self, engine: str) -> dict[str, object]:
        """Запустить вход: вернуть ссылку и режим завершения (code/callback)."""
        if engine not in LOGIN_ENGINES:
            return {"ok": False, "message": f"вход не поддерживается для {engine!r}"}
        self._stop(engine)  # перезапуск поверх прежней сессии — без утечки процесса
        try:
            proc = self._spawn(engine)
        except FileNotFoundError:
            return {"ok": False, "message": f"{engine} не установлен в образе"}
        except Exception as exc:  # pragma: no cover - неожиданный сбой старта
            return {"ok": False, "message": f"не удалось запустить вход: {exc}"}
        self._active[engine] = proc
        url = proc.read(URL_RE, self._url_timeout)
        if not url:
            self._stop(engine)
            return {"ok": False, "message": "не удалось получить ссылку входа"}
        url = url.rstrip(".,;)")  # отрезать пунктуацию, прилипшую из текста
        mode = LOGIN_ENGINES[engine]
        out: dict[str, object] = {"ok": True, "url": url, "mode": mode}
        if mode == "device":  # codex показывает одноразовый код рядом со ссылкой
            out["code"] = proc.read(DEVICE_CODE_RE, 5.0) or ""
        return out

    def submit(self, engine: str, code: str = "") -> dict[str, object]:
        """Завершить вход: для 'code' отправить код, дождаться токена/выхода.

        Успешный токен пишется в `.env` под ключ движка; сессия закрывается.
        """
        proc = self._active.get(engine)
        if proc is None:
            return {"ok": False, "message": "сессия входа не начата — нажмите «Войти»"}
        try:
            if code:
                proc.submit_code(code)
            res = proc.result(self._result_timeout)
            if res.ok and res.token and engine in _TOKEN_ENV_KEY:
                merge_env(self._envfile, {_TOKEN_ENV_KEY[engine]: res.token})
            return {"ok": res.ok, "message": res.message}
        finally:
            self._stop(engine)

    def _stop(self, engine: str) -> None:
        proc = self._active.pop(engine, None)
        if proc is not None:
            try:
                proc.stop()
            except Exception:  # pragma: no cover - завершение best-effort
                pass


# ── Реальный процесс входа (вне юнит-тестов) ──────────────────────────────────

# claude/codex — полноэкранные TUI: без TTY они не печатают ничего, а ссылку/токен
# терминал переносит по ширине окна. Поэтому процесс запускается под PTY с очень
# широким окном (URL и токен не разрываются), а ANSI-последовательности срезаются.
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"  # CSI (включая ?-приватные, напр. ?25h)
    r"|\x1b[\]PX^_][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC/DCS до терминатора
    r"|\x1b[@-Z\\-_=>78]"  # двухсимвольные escape
)
_PTY_COLS = 4000  # шире любой ссылки/токена — чтобы терминал не переносил строку


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class _PtyLogin:  # pragma: no cover - реальный процесс/PTY/IO
    """Запуск CLI-входа под PTY: фоновый поток копит очищенный вывод, методы сканируют.

    Реальная граница — в юнит-тестах подменяется фейком через `LoginSpawner`.
    """

    def __init__(self, engine: str, argv: list[str], env: dict[str, str]) -> None:
        import fcntl
        import os
        import pty
        import struct
        import subprocess
        import termios
        import threading

        self._engine = engine
        self._buf = ""
        self._lock = threading.Lock()
        self._os = os

        self._master, slave = pty.openpty()
        # Широкое и высокое окно: ссылка/токен печатаются одной строкой.
        winsize = struct.pack("HHHH", 200, _PTY_COLS, 0, 0)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, winsize)
        self._proc = subprocess.Popen(
            argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave)
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        while True:
            try:
                data = self._os.read(self._master, 4096)
            except OSError:
                break  # EIO после выхода процесса
            if not data:
                break
            text = _strip_ansi(data.decode("utf-8", "replace"))
            with self._lock:
                self._buf += text

    def _scan(self, pattern: re.Pattern[str]) -> str | None:
        with self._lock:
            m = pattern.search(self._buf)
            return m.group(0) if m else None

    def _wait_for(self, pattern: re.Pattern[str], timeout: float) -> str | None:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hit = self._scan(pattern)
            if hit:
                return hit
            if self._proc.poll() is not None:
                return self._scan(pattern)  # последний шанс после выхода
            time.sleep(0.2)
        return None

    def read(self, pattern: re.Pattern[str], timeout: float) -> str | None:
        return self._wait_for(pattern, timeout)

    def submit_code(self, code: str) -> None:
        # Ввод в TUI завершается Enter — в raw-TTY это возврат каретки.
        self._os.write(self._master, (code.strip() + "\r").encode("utf-8"))

    def result(self, timeout: float) -> LoginResult:
        import time

        if self._engine == "claude":
            # Ждём токен ИЛИ признак ошибки обмена — иначе при неверном/истёкшем
            # коде claude висит на «Press Enter to retry» и мы ждали бы весь таймаут.
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                token = self._scan(CLAUDE_TOKEN_RE)
                if token:
                    return LoginResult(True, "токен получен и сохранён", token=token)
                if self._scan(LOGIN_ERROR_RE):
                    return LoginResult(
                        False, "код неверный или истёк — нажмите «Войти» и повторите"
                    )
                if self._proc.poll() is not None:
                    break
                time.sleep(0.3)
            token = self._scan(CLAUDE_TOKEN_RE)
            if token:
                return LoginResult(True, "токен получен и сохранён", token=token)
            return LoginResult(False, "токен не получен — нажмите «Войти» и повторите")
        # codex: ждём успешного выхода процесса (auth.json пишет сам)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rc = self._proc.poll()
            if rc is not None:
                if rc == 0:
                    return LoginResult(True, "вход выполнен")
                return LoginResult(False, f"вход не удался (код {rc})")
            time.sleep(0.3)
        return LoginResult(False, "вход ещё не подтверждён — авторизуйтесь в браузере")

    def stop(self) -> None:
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
        finally:
            try:
                self._os.close(self._master)
            except OSError:
                pass


def default_spawner(envfile: Path | str) -> LoginSpawner:  # pragma: no cover - IO
    """Спавнер реальных процессов: env берётся из окружения + `.env`.

    `TERM` задаётся (CLI-агенты ждут терминал), браузер не открываем — нужна только
    ссылка для пользователя.
    """
    import os

    from .env_store import parse_env

    def spawn(engine: str) -> LoginProcess:
        env = {**os.environ, **parse_env(envfile)}
        env.setdefault("TERM", "xterm-256color")
        return _PtyLogin(engine, LOGIN_ARGV[engine], env)

    return spawn
