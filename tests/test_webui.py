"""Тесты дизайн-каркаса web-UI (Task 5.0).

Без сети: TestClient (starlette/httpx) гоняет ASGI-приложение в памяти.
Проверяем: страница рендерится, CSS-переменные присутствуют, иконки грузятся
локальным путём (не cdn.jsdelivr.net), компоненты берут цвета из presentation.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from webui import create_app
from webui.components import badge, card, chip, track_tag, verdict_line
from webui.render import render_results, vacancy_card

from job_agent.models import (
    EnrichedResult,
    Gaps,
    Requirements,
    ScoreResult,
    Scores,
    Vacancy,
    Verdict,
)
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


# ── Экран 1 «Настройка» (Task 5.1) ────────────────────────────────


def test_settings_screen_inventory(client: TestClient) -> None:
    body = client.get("/").text
    # шапка с ti-radar-2 и заголовок «Профиль» (без «под два пути»)
    assert "ti-radar-2" in body
    assert "Профиль" in body
    assert "под два пути" not in body
    assert "Скейлап" not in body and "AI-first" not in body  # нет хардкода путей
    # always-on warning + повторяемая карточка + добавление направления
    assert "always-on" in body
    assert 'id="tracks-list"' in body
    assert 'id="add-track"' in body
    assert 'id="track-template"' in body
    # движок AI: три карточки, CLI дефолт с бейджем
    for value in ('value="cli"', 'value="api_key"', 'value="ollama"'):
        assert value in body
    assert "дефолт" in body
    # выхлоп: чипы и слайдер порога с живым %
    assert 'name="out_table"' in body and 'name="out_bot"' in body
    assert 'name="cover_threshold"' in body
    assert "70%" in body
    # низ: сохранить + запустить backfill
    assert 'value="save"' in body and 'value="backfill"' in body
    # скрипт интерактивности грузится локально
    assert "/static/js/settings.js" in body


def test_settings_default_engine_is_cli(client: TestClient) -> None:
    body = client.get("/").text
    # дефолтный движок отмечен checked именно на CLI
    cli = body.split('value="cli"', 1)[1][:40]
    assert "checked" in cli


def _single_track_form() -> dict[str, str]:
    return {
        "track_name": "Backend",
        "track_resume": "./resumes/backend.pdf",
        "track_template": "./cover-templates/default.md",
        "track_rubric": "Сильная инженерная команда",
        "track_roles": "Backend Engineer, Tech Lead",
        "engine": "cli",
        "cli_tool": "claude",
        "out_table": "on",
        "out_bot": "on",
        "bot_token": "123:abc",
        "cover_threshold": "75",
        "use_aggregators": "on",
        "search_map_path": "./search-map.md",
        "web_search_url": "http://localhost:8080",
        "action": "save",
    }


def test_save_single_track_writes_valid_config(tmp_path: Path) -> None:
    from job_agent.config import load_config

    cfg_path = tmp_path / "config.json"
    client = TestClient(create_app(config_path=cfg_path))
    r = client.post("/save", data=_single_track_form())
    assert r.status_code == 200
    assert "Конфиг сохранён" in r.text
    assert cfg_path.exists()
    cfg = load_config(cfg_path)  # валиден по схеме + pydantic
    assert cfg.is_single_track
    assert cfg.tracks[0].name == "Backend"
    assert cfg.tracks[0].id == "backend"
    assert cfg.tracks[0].role_gate == ["Backend Engineer", "Tech Lead"]
    assert cfg.output_mode == "both"
    assert cfg.cover_letter_threshold == 75
    assert cfg.scoring_engine == "cli" and cfg.cli_tool == "claude"


def test_save_three_tracks_writes_valid_config(tmp_path: Path) -> None:
    from job_agent.config import load_config

    cfg_path = tmp_path / "config.json"
    client = TestClient(create_app(config_path=cfg_path))
    # повторяющиеся поля — три направления (UI клонирует карточку)
    data = {
        "track_name": ["Backend", "Скейлап", "AI"],  # кириллица → id-фолбэк
        "track_resume": ["./r/backend.pdf", "./r/scaleup.pdf", "./r/ai.pdf"],
        "track_template": ["", "", ""],
        "track_rubric": ["", "", ""],
        "track_roles": ["", "", ""],
        "engine": "ollama",
        "ollama_model": "llama3.1:70b",
        "out_table": "on",
        "cover_threshold": "70",
        "action": "backfill",
    }
    r = client.post("/save", data=data)
    assert r.status_code == 200
    cfg = load_config(cfg_path)
    assert len(cfg.tracks) == 3
    ids = [t.id for t in cfg.tracks]
    assert ids == ["backend", "track-2", "ai"]  # кириллица схлопывается в фолбэк
    assert cfg.output_mode == "table"
    assert cfg.scoring_engine == "ollama" and cfg.ollama_model == "llama3.1:70b"


def test_save_invalid_config_rejected_keeps_no_file(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    client = TestClient(create_app(config_path=cfg_path))
    # пустая форма: нет ни одного трека → невалидно (minItems: 1)
    r = client.post("/save", data={"engine": "cli", "out_table": "on"})
    assert r.status_code == 400
    assert "не сохранён" in r.text
    assert not cfg_path.exists()  # битый сабмит не создаёт файл


# ── Экран 2 «Подборка» (Task 5.2) ─────────────────────────────────


def _enriched(
    *,
    title: str = "Backend Engineer",
    overall: int = 86,
    map_fit: int = 60,
    track: str = "Бэкенд",
    verdict_type: str = "precise_fit",
    summary: str = "точное попадание",
    company: str | None = "Acme",
    link: str | None = "@hr",
    url: str | None = "https://t.me/jobs/1",
    cover_letter: str | None = None,
    critical: list[str] | None = None,
) -> EnrichedResult:
    vacancy = Vacancy(
        title=title,
        company=company,
        link_or_contact=link,
        salary="300к",
        description="desc",
        source="@jobs",
        url=url,
        date=datetime(2026, 6, 1, 12, 0),
    )
    score = ScoreResult(
        track=track,
        company_analysis="scaleup",
        company_confidence="medium",
        requirements=Requirements(must=["Python"], nice=["k8s"]),
        matching=[],
        scores=Scores(
            must=80, nice=50, seniority=70, context=65, overall=overall, map_fit=map_fit
        ),
        score_method="среднее",
        gaps=Gaps(
            critical=["нет k8s"] if critical is None else critical,
            strategic=["масштаб"],
            cosmetic=[],
        ),
        to_reach_100=[],
        verdict=Verdict(
            should_apply=True,
            type=verdict_type,
            hr_screening_probability="high",
            final_stage_probability="medium",
            summary=summary,
        ),
    )
    return EnrichedResult(vacancy=vacancy, score=score, cover_letter=cover_letter)


def test_vacancy_card_inventory() -> None:
    html = vacancy_card(_enriched(overall=86, map_fit=72))
    # должность, мета (компания · стадия), бейдж зелёного диапазона, карта
    assert "Backend Engineer" in html
    assert "Acme · scaleup" in html
    assert BADGE_COLORS["green"].bg in html
    assert "ti-map-2" in html and "карта 72%" in html
    # вердикт точного попадания с иконкой и кнопка «Открыть»
    assert "ti-circle-check" in html
    assert "ti-external-link" in html and "Открыть" in html
    # гэп
    assert "Гэп: нет k8s" in html


def test_vacancy_card_track_tag_hidden_when_single() -> None:
    multi = vacancy_card(_enriched(track="Бэкенд"), is_single_track=False)
    single = vacancy_card(_enriched(track="Бэкенд"), is_single_track=True)
    assert "track-tag" in multi and "Бэкенд" in multi
    assert "track-tag" not in single


def test_vacancy_card_cover_button_conditional() -> None:
    # выше порога + есть письмо → кнопка «Сопроводительное»
    above = vacancy_card(
        _enriched(overall=85, cover_letter="Здравствуйте..."),
        cover_letter_threshold=70,
    )
    assert "Сопроводительное" in above and "ti-copy" in above
    # ниже порога → кнопки нет, даже если письмо есть
    below = vacancy_card(
        _enriched(overall=60, cover_letter="Здравствуйте..."),
        cover_letter_threshold=70,
    )
    assert "Сопроводительное" not in below
    # выше порога, но письма нет → кнопки нет
    no_letter = vacancy_card(
        _enriched(overall=85, cover_letter=None), cover_letter_threshold=70
    )
    assert "Сопроводительное" not in no_letter


def test_render_results_sorted_and_header() -> None:
    results = [
        _enriched(title="Low", overall=55),
        _enriched(title="High", overall=92),
        _enriched(title="Mid", overall=74),
    ]
    html = render_results(
        results, run_date="28.06.2026", collected=120, after_filter=18
    )
    # шапка прогона со статистикой и кнопкой скачивания
    assert "Подборка · 28.06.2026" in html
    assert "собрано 120 · после фильтра 18 · топ-3" in html
    assert "ti-download" in html and "Скачать .xlsx" in html
    # карточки по убыванию overall
    assert html.index("High") < html.index("Mid") < html.index("Low")


def test_render_results_empty_state() -> None:
    html = render_results([])
    assert "topbar" not in html  # просто гладкий рендер
    assert "Прогон ещё не выполнялся" in html
    assert "собрано 0 · после фильтра 0 · топ-0" in html


def test_render_results_top_k_limits_shown() -> None:
    results = [_enriched(title=f"V{i}", overall=90 - i) for i in range(5)]
    html = render_results(results, top_k=2)
    assert "топ-2" in html
    assert "V0" in html and "V1" in html
    assert "V4" not in html


def test_results_route_renders(client: TestClient) -> None:
    r = client.get("/results")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "Подборка" in body
    assert 'class="col"' in body or "class=col" in body
