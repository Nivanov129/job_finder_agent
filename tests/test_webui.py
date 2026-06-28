"""Тесты дизайн-каркаса web-UI (Task 5.0).

Без сети: TestClient (starlette/httpx) гоняет ASGI-приложение в памяти.
Проверяем: страница рендерится, CSS-переменные присутствуют, иконки грузятся
локальным путём (не cdn.jsdelivr.net), компоненты берут цвета из presentation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from webui import create_app
from webui.components import badge, card, chip, track_tag, verdict_line

from job_agent.presentation import BADGE_COLORS, TRACK_TAG_COLORS

STATIC = Path(__file__).resolve().parents[1] / "webui" / "static"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_index_renders(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # единственный столбец и шапка-каркас
    assert 'class="col"' in body or "class=col" in body
    assert "ti-radar-2" in body


def test_index_no_cdn(client: TestClient) -> None:
    body = client.get("/").text
    assert "cdn.jsdelivr.net" not in body
    # иконки/стили — локальным путём
    assert "/static/css/tabler-icons.css" in body
    assert "/static/css/tokens.css" in body


def test_tokens_css_has_variables(client: TestClient) -> None:
    r = client.get("/static/css/tokens.css")
    assert r.status_code == 200
    css = r.text
    assert ":root" in css
    for var in (
        "--surface-0",
        "--surface-1",
        "--surface-2",
        "--text-primary",
        "--border",
        "--text-accent",
        "--radius",
    ):
        assert var in css, f"нет CSS-переменной {var}"
    # бордеры 0.5px и радиус карточки 12px из токенов
    assert "0.5px" in css
    assert "12px" in css


def test_tabler_css_local_only(client: TestClient) -> None:
    r = client.get("/static/css/tabler-icons.css")
    assert r.status_code == 200
    css = r.text
    assert "cdn.jsdelivr.net" not in css
    assert "@font-face" in css
    # webfont ссылается на локальный woff2, не на CDN
    assert "tabler-icons.woff2" in css
    assert "fonts/tabler-icons.woff2" in css


def test_font_served_locally(client: TestClient) -> None:
    r = client.get("/static/fonts/tabler-icons.woff2")
    assert r.status_code == 200
    # реальный woff2 (магия wOF2)
    assert r.content[:4] == b"wOF2"


def test_font_file_vendored() -> None:
    assert (STATIC / "fonts" / "tabler-icons.woff2").exists()


def test_badge_uses_presentation_colors() -> None:
    html = badge(86)
    assert BADGE_COLORS["green"].bg in html
    assert BADGE_COLORS["green"].fg in html
    assert "86%" in html
    # янтарный и серый диапазоны
    assert BADGE_COLORS["amber"].bg in badge(74)
    assert BADGE_COLORS["grey"].bg in badge(50)


def test_track_tag_colors() -> None:
    html = track_tag("AI-инженер")
    assert TRACK_TAG_COLORS.bg in html
    assert "AI-инженер" in html


def test_chip_on_state() -> None:
    assert "chip--on" in chip("vseti.app", on=True)
    assert "chip--on" not in chip("getmatch")


def test_verdict_line_icon_by_type() -> None:
    assert "ti-circle-check" in verdict_line("precise_fit", "ок", overall=90)
    assert "ti-arrow-up-right" in verdict_line("stretch", "тянись", overall=75)
    # ниже зоны → фолбэк «на грани»
    assert "ti-minus" in verdict_line("precise_fit", "", overall=40)


def test_card_escapes_and_embeds() -> None:
    html = card(title="A&B", meta="x", right=badge(90), body="<b>ok</b>")
    assert "A&amp;B" in html  # экранирование заголовка
    assert "card__title" in html


def test_components_escape_user_text() -> None:
    assert "<script>" not in chip("<script>")
    assert "&lt;script&gt;" in chip("<script>")
