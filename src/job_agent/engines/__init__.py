"""AI-движки скоринга (BYO) — интерфейс, фейк и фабрика.

`make_engine(config)` выбирает адаптер по `config.scoring_engine`:
`cli` (Claude Code/Codex), `api_key` (Anthropic/OpenAI), `ollama` (локально).
Конкретные адаптеры подгружаются лениво (Task 1.5) — фабрика остаётся тонкой.
Тесты подменяют движок через `FakeEngine` или параметр `override`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..config import ConfigError
from .base import Engine
from .fake import FakeEngine

if TYPE_CHECKING:
    from ..config import Config

__all__ = ["Engine", "FakeEngine", "KNOWN_ENGINES", "make_engine"]

# Имена движков из `config.schema.json` (enum scoring_engine).
KNOWN_ENGINES: tuple[str, ...] = ("cli", "api_key", "ollama")


def make_engine(config: Config, *, override: Engine | None = None) -> Engine:
    """Построить движок по `config.scoring_engine`.

    `override` (или инъекция `FakeEngine`) имеет приоритет — для тестов и
    пайплайна. Неизвестное имя движка → внятная `ConfigError`.
    """
    if override is not None:
        return override

    engine = config.scoring_engine
    if engine not in KNOWN_ENGINES:
        known = ", ".join(KNOWN_ENGINES)
        raise ConfigError(
            f"неизвестный scoring_engine {engine!r}; ожидается один из: {known}"
        )

    if engine == "cli":
        from .cli import CliEngine

        return CliEngine.from_config(config)
    if engine == "api_key":
        from .api_key import ApiKeyEngine

        return ApiKeyEngine.from_config(config)
    from .ollama import OllamaEngine

    return OllamaEngine.from_config(config)
