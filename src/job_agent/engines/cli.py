"""CLI-движок: shell-out к установленному агенту (`claude` / `codex`).

Дефолтный BYO-вариант — пользователь уже залогинен в Claude Code или Codex на
подписке, ключи не нужны. Реальный вызов процесса спрятан за фасадом `Runner`
(argv → stdout); в тестах он подменяется фейком, юнит-тесты процессы не запускают.
Чистая функция `build_argv` собирает командную строку — её и тестируем.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ..config import ConfigError
from .base import Engine

if TYPE_CHECKING:
    from ..config import Config

__all__ = ["CliEngine", "Runner", "build_argv", "KNOWN_CLI_TOOLS"]

# Поддерживаемые CLI-инструменты (enum cli_tool в config.schema.json).
KNOWN_CLI_TOOLS: tuple[str, ...] = ("claude", "codex")

# argv -> stdout. Дефолт запускает процесс; в тестах подменяется фейком.
Runner = Callable[[list[str]], str]


def build_argv(
    cli_tool: str, prompt: str, *, web_search: bool = False, output_file: str | None = None
) -> list[str]:
    """Собрать командную строку неинтерактивного запуска агента.

    `claude -p <prompt>` печатает ответ в stdout. `codex exec` печатает
    человекочитаемый баннер + ЭХО ПРОМТА вокруг ответа, поэтому чистый ответ
    берём не из stdout, а из файла `--output-last-message` (`output_file`); ещё
    нужны `--skip-git-repo-check` (запуск вне git-репо) и `--color never`.

    Оба инструмента ведут web-поиск встроенными средствами — флаг `web_search`
    на argv не влияет, принимается для единообразия контракта `Engine`.
    """
    del web_search  # web-поиск встроен в сам агент; на argv не влияет
    if cli_tool == "claude":
        return ["claude", "-p", prompt]
    if cli_tool == "codex":
        argv = ["codex", "exec", "--skip-git-repo-check", "--color", "never"]
        if output_file:
            argv += ["--output-last-message", output_file]
        argv.append(prompt)
        return argv
    known = ", ".join(KNOWN_CLI_TOOLS)
    raise ConfigError(f"неизвестный cli_tool {cli_tool!r}; ожидается один из: {known}")


def _subprocess_runner(argv: list[str]) -> str:  # pragma: no cover - реальный процесс
    """Запустить процесс и вернуть stdout (вне юнит-тестов). stdin закрыт — codex
    иначе ждёт ввод из stdin и подвисает."""
    import subprocess

    result = subprocess.run(
        argv, capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL
    )
    return result.stdout


class CliEngine(Engine):
    """Движок поверх локального CLI-агента (`claude` / `codex`)."""

    def __init__(self, cli_tool: str, *, runner: Runner | None = None) -> None:
        if cli_tool not in KNOWN_CLI_TOOLS:
            known = ", ".join(KNOWN_CLI_TOOLS)
            raise ConfigError(
                f"неизвестный cli_tool {cli_tool!r}; ожидается один из: {known}"
            )
        self._cli_tool = cli_tool
        self._runner = runner or _subprocess_runner

    @classmethod
    def from_config(cls, config: Config, *, runner: Runner | None = None) -> CliEngine:
        if not config.cli_tool:
            raise ConfigError(
                "scoring_engine='cli' требует поля 'cli_tool' (claude|codex)"
            )
        return cls(config.cli_tool, runner=runner)

    def complete(self, prompt: str, *, web_search: bool = False) -> str:
        if self._cli_tool == "codex":
            return self._complete_codex(prompt)
        argv = build_argv(self._cli_tool, prompt, web_search=web_search)
        return self._runner(argv).strip()

    def _complete_codex(self, prompt: str) -> str:
        """codex exec: чистый ответ читаем из файла `--output-last-message`.

        stdout (баннер + эхо промта) игнорируем — иначе парсер JSON цепляет скобки
        из эха схемы. Если файл пуст (фейк-runner в тестах) — фолбэк на stdout.
        """
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".txt", prefix="codex-out-")
        os.close(fd)
        try:
            argv = build_argv("codex", prompt, output_file=path)
            stdout = self._runner(argv)
            try:
                with open(path, encoding="utf-8") as fh:
                    message = fh.read().strip()
            except OSError:
                message = ""
            return message or stdout.strip()
        finally:
            try:
                os.unlink(path)
            except OSError:  # pragma: no cover - уборка best-effort
                pass
