"""Web-поиск — интерфейс, фейк и фабрика.

`make_searcher(config)` выбирает адаптер по `config.web_search.provider`:
`searxng` (self-host) или `serp` (облачный ключ). Конкретные адаптеры
подгружаются лениво — фабрика остаётся тонкой. Тесты подменяют поиск через
`FakeSearcher` или параметр `override`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..config import ConfigError
from .base import Searcher, SearchResult
from .fake import FakeSearcher

if TYPE_CHECKING:
    from ..config import Config

__all__ = [
    "Searcher",
    "SearchResult",
    "FakeSearcher",
    "KNOWN_PROVIDERS",
    "make_searcher",
]

# Имена провайдеров из `config.schema.json` (enum web_search.provider).
KNOWN_PROVIDERS: tuple[str, ...] = ("searxng", "serp")


def make_searcher(config: Config, *, override: Searcher | None = None) -> Searcher:
    """Построить web-поиск по `config.web_search.provider`.

    `override` (или инъекция `FakeSearcher`) имеет приоритет — для тестов и
    пайплайна. Неизвестный/ненастроенный провайдер → внятная `ConfigError`.
    """
    if override is not None:
        return override

    # Секция необязательна: по умолчанию — searxng (адрес берёт из env/дефолта),
    # чтобы web-поиск работал без ручной настройки.
    ws = config.web_search
    provider = ws.provider if ws is not None else "searxng"
    if provider not in KNOWN_PROVIDERS:
        known = ", ".join(KNOWN_PROVIDERS)
        raise ConfigError(
            f"неизвестный web_search.provider {provider!r}; ожидается один из: {known}"
        )

    if provider == "searxng":
        from .searxng import SearxngSearcher

        return SearxngSearcher.from_config(config)
    from .serp import SerpSearcher

    return SerpSearcher.from_config(config)
