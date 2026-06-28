"""Тесты общих констант представления: границы диапазонов и маппинг вердиктов."""

from __future__ import annotations

import pytest

from job_agent.presentation import (
    BADGE_COLORS,
    BORDERLINE_STYLE,
    TRACK_TAG_COLORS,
    VERDICT_STYLES,
    badge_band,
    badge_colors,
    to_argb,
    verdict_style,
)


@pytest.mark.parametrize(
    ("overall", "band"),
    [
        (100, "green"),
        (80, "green"),
        (79, "amber"),
        (70, "amber"),
        (69, "grey"),
        (0, "grey"),
    ],
)
def test_badge_band_default_boundaries(overall: int, band: str) -> None:
    assert badge_band(overall) == band


def test_badge_band_custom_thresholds() -> None:
    assert badge_band(75, green_min=90, amber_min=60) == "amber"
    assert badge_band(95, green_min=90, amber_min=60) == "green"
    assert badge_band(50, green_min=90, amber_min=60) == "grey"


def test_badge_band_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError, match="amber_min"):
        badge_band(50, green_min=60, amber_min=70)


def test_badge_colors_shortcut_matches_band() -> None:
    assert badge_colors(85) is BADGE_COLORS["green"]
    assert badge_colors(72) is BADGE_COLORS["amber"]
    assert badge_colors(10) is BADGE_COLORS["grey"]


def test_badge_colors_hex_values() -> None:
    assert BADGE_COLORS["green"].bg == "#EAF3DE"
    assert BADGE_COLORS["green"].fg == "#27500A"
    assert BADGE_COLORS["amber"].bg == "#FAEEDA"
    assert BADGE_COLORS["grey"].bg == "#F1EFE8"
    assert TRACK_TAG_COLORS.bg == "#EEEDFE"
    assert TRACK_TAG_COLORS.fg == "#3C3489"


def test_verdict_style_by_type() -> None:
    assert verdict_style("precise_fit") is VERDICT_STYLES["precise_fit"]
    assert verdict_style("precise_fit").icon == "ti-circle-check"
    assert verdict_style("stretch").icon == "ti-arrow-up-right"
    assert verdict_style("stretch").tone_var == "--text-warning"


def test_verdict_style_borderline_when_below_zone() -> None:
    # тип «точное попадание», но overall ниже янтарной зоны → «на грани»
    assert verdict_style("precise_fit", overall=65) is BORDERLINE_STYLE
    assert verdict_style("stretch", overall=69) is BORDERLINE_STYLE
    # в зоне — стиль по типу
    assert verdict_style("precise_fit", overall=70) is VERDICT_STYLES["precise_fit"]


def test_verdict_style_unknown_type_falls_back() -> None:
    assert verdict_style("maybe") is BORDERLINE_STYLE


def test_to_argb() -> None:
    assert to_argb("#EAF3DE") == "FFEAF3DE"
    assert to_argb("eaf3de") == "FFEAF3DE"
