"""Детерминированный фейковый движок для юнит-тестов (без сети).

Возвращает заранее заданный ответ (строку, очередь строк или вызываемое по
промту) и записывает все вызовы — стадии нормализации/скоринга тестируются на
нём без обращения к реальному LLM.
"""

from __future__ import annotations

from collections.abc import Callable

from .base import Engine

__all__ = ["FakeEngine"]


class FakeEngine(Engine):
    """Фейк движка с записью вызовов.

    - `response` — строка (вернётся всегда) или функция `prompt -> str`.
    - `responses` — очередь ответов; каждый вызов снимает следующий по порядку.
    """

    def __init__(
        self,
        response: str | Callable[[str], str] = "",
        *,
        responses: list[str] | None = None,
    ) -> None:
        self._response = response
        self._responses = list(responses) if responses is not None else None
        self.calls: list[tuple[str, bool]] = []

    def complete(self, prompt: str, *, web_search: bool = False) -> str:
        self.calls.append((prompt, web_search))
        if self._responses is not None:
            if not self._responses:
                raise AssertionError("FakeEngine: очередь responses исчерпана")
            return self._responses.pop(0)
        if callable(self._response):
            return self._response(prompt)
        return self._response

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_prompt(self) -> str | None:
        return self.calls[-1][0] if self.calls else None
