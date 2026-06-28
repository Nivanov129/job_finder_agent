"""Общие константы представления — единственный источник цветового кодирования.

По `design/design-tokens.md`. Отсюда берут цвета и иконки и xlsx (Task 1.12),
и Telegram-бот (Task 2.3), и web-UI (Фаза 5). Дублировать палитру в этих модулях
нельзя — только импорт отсюда.

Что задаёт модуль:
- `badge_band(overall)` → `'green' | 'amber' | 'grey'` по диапазону (пороги
  конфигурируемы, дефолт ≥80 / 70–79 / <70 из прототипа);
- `BADGE_COLORS` — hex фон+текст бейджа «резюме %» для каждого диапазона
  (заливка xlsx и фон бейджа в web/боте); `TRACK_TAG_COLORS` — бейдж направления;
- `verdict_style(...)` — иконка Tabler + тон по `verdict.type` из `ScoreResult`,
  с фолбэком «на грани», когда `overall` ниже зоны.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "BadgeBand",
    "DEFAULT_GREEN_MIN",
    "DEFAULT_AMBER_MIN",
    "BandColors",
    "BADGE_COLORS",
    "TRACK_TAG_COLORS",
    "VerdictStyle",
    "VERDICT_STYLES",
    "BORDERLINE_STYLE",
    "badge_band",
    "badge_colors",
    "verdict_style",
    "to_argb",
]

BadgeBand = Literal["green", "amber", "grey"]

#: Дефолтные границы диапазонов бейджа (из прототипа). Конфигурируемы вызовом.
DEFAULT_GREEN_MIN = 80
DEFAULT_AMBER_MIN = 70


@dataclass(frozen=True)
class BandColors:
    """Пара hex-цветов бейджа: фон заливки и цвет текста."""

    bg: str
    fg: str


#: Цвета бейджа «резюме %» по диапазону (см. таблицу в design-tokens.md).
BADGE_COLORS: dict[BadgeBand, BandColors] = {
    "green": BandColors(bg="#EAF3DE", fg="#27500A"),
    "amber": BandColors(bg="#FAEEDA", fg="#633806"),
    "grey": BandColors(bg="#F1EFE8", fg="#444441"),
}

#: Бейдж тега направления (скрыт при единственном треке — решает вызывающий код).
TRACK_TAG_COLORS = BandColors(bg="#EEEDFE", fg="#3C3489")


@dataclass(frozen=True)
class VerdictStyle:
    """Представление вердикта: иконка Tabler, тон (CSS-переменная + hex), подпись."""

    icon: str
    tone_var: str
    tone_hex: str
    label: str


#: Стили по `verdict.type` из `ScoreResult.verdict`.
VERDICT_STYLES: dict[str, VerdictStyle] = {
    "precise_fit": VerdictStyle(
        icon="ti-circle-check",
        tone_var="--text-success",
        tone_hex="#3B6D11",
        label="Точное попадание · откликаться",
    ),
    "stretch": VerdictStyle(
        icon="ti-arrow-up-right",
        tone_var="--text-warning",
        tone_hex="#854F0B",
        label="Stretch · стоит откликнуться",
    ),
}

#: Фолбэк «на грани»: overall ниже зоны (серый диапазон) — решать по приоритету.
BORDERLINE_STYLE = VerdictStyle(
    icon="ti-minus",
    tone_var="--text-muted",
    tone_hex="#8a8980",
    label="На грани · решать по приоритету",
)


def badge_band(
    overall: int,
    *,
    green_min: int = DEFAULT_GREEN_MIN,
    amber_min: int = DEFAULT_AMBER_MIN,
) -> BadgeBand:
    """Диапазон бейджа «резюме %» по `overall`.

    `overall >= green_min` → зелёный; `>= amber_min` → янтарный; иначе серый.
    Пороги конфигурируемы; по умолчанию ≥80 / 70–79 / <70.
    """
    if amber_min > green_min:
        raise ValueError(
            f"amber_min ({amber_min}) не может быть выше green_min ({green_min})"
        )
    if overall >= green_min:
        return "green"
    if overall >= amber_min:
        return "amber"
    return "grey"


def badge_colors(
    overall: int,
    *,
    green_min: int = DEFAULT_GREEN_MIN,
    amber_min: int = DEFAULT_AMBER_MIN,
) -> BandColors:
    """Цвета бейджа (фон+текст) для `overall` — удобный шорткат над `badge_band`."""
    return BADGE_COLORS[badge_band(overall, green_min=green_min, amber_min=amber_min)]


def verdict_style(
    verdict_type: str,
    *,
    overall: int | None = None,
    amber_min: int = DEFAULT_AMBER_MIN,
) -> VerdictStyle:
    """Иконка+тон по `verdict.type`.

    Если `overall` передан и ниже зоны (серый диапазон, `< amber_min`) — отдаём
    «на грани» (`ti-minus`, muted) независимо от типа. Иначе — стиль по типу;
    неизвестный тип также схлопывается в «на грани».
    """
    if overall is not None and overall < amber_min:
        return BORDERLINE_STYLE
    return VERDICT_STYLES.get(verdict_type, BORDERLINE_STYLE)


def to_argb(hex_color: str) -> str:
    """`#RRGGBB` → `FFRRGGBB` для openpyxl `PatternFill` (непрозрачная заливка)."""
    return "FF" + hex_color.lstrip("#").upper()
