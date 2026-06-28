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
    "default_spawner",
    "LOGIN_ARGV",
]

# Команда входа на движок (неинтерактивный запуск пишет в stdin/stdout).
LOGIN_ARGV: dict[str, list[str]] = {
    "claude": ["claude", "setup-token"],
    "codex": ["codex", "login"],
}

# Движки с server-driven входом и режим завершения: code — ввод кода + токен в
# stdout (claude); callback — вход завершается в браузере, ждём выход (codex).
LOGIN_ENGINES: dict[str, str] = {"claude": "code", "codex": "callback"}
# Куда кладётся пойманный токен (codex токен не печатает — пишет auth.json сам).
_TOKEN_ENV_KEY: dict[str, str] = {"claude": "CLAUDE_CODE_OAUTH_TOKEN"}

URL_RE = re.compile(r"https?://[^\s'\"<>]+")
CLAUDE_TOKEN_RE = re.compile(r"sk-ant-oat[0-9A-Za-z_-]+")


@dataclass
class LoginResult:
    """Итог входа: успех/ошибка, сообщение и (для claude) пойманный токен."""

    ok: bool
    message: str
    token: str | None = None


class LoginProcess(Protocol):
    """Интерфейс запущенного процесса входа (реальный Popen или фейк в тестах)."""

    def read_url(self, timeout: float) -> str | None:
        """Дождаться и вернуть OAuth-ссылку из вывода (или None по таймауту)."""
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
        url = proc.read_url(self._url_timeout)
        if not url:
            self._stop(engine)
            return {"ok": False, "message": "не удалось получить ссылку входа"}
        return {"ok": True, "url": url, "mode": LOGIN_ENGINES[engine]}

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


class _PopenLogin:  # pragma: no cover - реальный процесс/IO
    """Обёртка над `subprocess.Popen`: фоновый поток копит вывод, методы сканируют.

    Реальная граница — в юнит-тестах подменяется фейком через `LoginSpawner`.
    """

    def __init__(self, engine: str, argv: list[str], env: dict[str, str]) -> None:
        import subprocess
        import threading

        self._engine = engine
        self._buf = ""
        self._lock = threading.Lock()
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            with self._lock:
                self._buf += line

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

    def read_url(self, timeout: float) -> str | None:
        return self._wait_for(URL_RE, timeout)

    def submit_code(self, code: str) -> None:
        if self._proc.stdin:
            self._proc.stdin.write(code.rstrip("\n") + "\n")
            self._proc.stdin.flush()

    def result(self, timeout: float) -> LoginResult:
        import time

        if self._engine == "claude":
            token = self._wait_for(CLAUDE_TOKEN_RE, timeout)
            if token:
                return LoginResult(True, "токен получен и сохранён", token=token)
            return LoginResult(False, "токен не получен — проверьте код и повторите")
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
        except Exception:
            pass


def default_spawner(envfile: Path | str) -> LoginSpawner:  # pragma: no cover - IO
    """Спавнер реальных процессов: env берётся из окружения + `.env`."""
    import os

    from .env_store import parse_env

    def spawn(engine: str) -> LoginProcess:
        env = {**os.environ, **parse_env(envfile)}
        return _PopenLogin(engine, LOGIN_ARGV[engine], env)

    return spawn
