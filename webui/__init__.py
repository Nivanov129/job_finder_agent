"""Web-UI (опц., Фаза 5) — FastAPI + статика.

Ядро работает headless без этого пакета. Визуальный язык — `design/design-tokens.md`;
структура обобщается под `tracks[]`. Иконки Tabler вшиты локально (`static/fonts/`),
не с CDN. Цветовое кодирование — только из `job_agent.presentation`.
"""

from __future__ import annotations

from webui.app import create_app

__all__ = ["create_app"]
