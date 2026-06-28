"""Интерфейс AI-движка скоринга (BYO).

Все стадии, которым нужен LLM (нормализация, скоринг, обогащение), работают
только через этот контракт. Конкретные адаптеры (`cli`, `api_key`, `ollama`)
живут отдельными модулями за фасадом; сетевые вызовы и секреты не торчат наружу.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

__all__ = ["Engine"]


class Engine(ABC):
    """AI-движок: один синхронный вызов «промт → текст»."""

    @abstractmethod
    def complete(self, prompt: str, *, web_search: bool = False) -> str:
        """Выполнить промт и вернуть сырой текст ответа.

        `web_search=True` — движку разрешён web-поиск на время вызова (для
        анализа компании на стадии скоринга). Парсинг/валидация ответа — на
        вызывающей стадии, не здесь.
        """
        raise NotImplementedError
