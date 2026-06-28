"""Тесты Telegram-бот выхода (стадия 7) — без сети, через фейк-транспорт."""

from __future__ import annotations

from datetime import datetime

from job_agent.models import (
    ContactCandidate,
    ContactResult,
    EnrichedResult,
    Gaps,
    Requirements,
    ScoreResult,
    Scores,
    Vacancy,
    Verdict,
)
from job_agent.output.bot import (
    BotTransport,
    Card,
    build_card,
    render_digest,
    send_digest,
)
from job_agent.presentation import badge_band, verdict_style


def _enriched(
    *,
    title: str,
    overall: int,
    track: str = "Бэкенд",
    map_fit: int = 50,
    verdict_type: str = "precise_fit",
    summary: str = "точное попадание",
    company: str | None = "Acme",
    link: str | None = "@hr",
    url: str | None = "https://t.me/jobs/1",
    cover_letter: str | None = None,
    contacts: ContactResult | None = None,
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
            must=80,
            nice=50,
            seniority=70,
            context=65,
            overall=overall,
            map_fit=map_fit,
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
    return EnrichedResult(
        vacancy=vacancy,
        score=score,
        cover_letter=cover_letter,
        contacts=contacts,
    )


class _FakeTransport(BotTransport):
    """Записывает отправленные карточки вместо сетевого вызова."""

    def __init__(self) -> None:
        self.sent: list[tuple[int | str, Card]] = []

    def send_card(self, chat_id: int | str, card: Card) -> None:
        self.sent.append((chat_id, card))


def _kinds(card: Card) -> list[str]:
    return [b.kind for b in card.buttons]


def test_card_header_is_title_at_company() -> None:
    card = build_card(_enriched(title="Бэкенд-разработчик", overall=85))
    assert card.text.splitlines()[0] == "Бэкенд-разработчик @ Acme"


def test_header_without_company() -> None:
    card = build_card(_enriched(title="Бэкенд", overall=85, company=None))
    assert card.text.splitlines()[0] == "Бэкенд"


def test_track_tag_present_with_multiple_tracks() -> None:
    card = build_card(_enriched(title="A", overall=85), is_single_track=False)
    assert "#Бэкенд" in card.text


def test_track_tag_hidden_when_single_track() -> None:
    card = build_card(_enriched(title="A", overall=85), is_single_track=True)
    assert "#Бэкенд" not in card.text


def test_percent_line_has_both_scores() -> None:
    card = build_card(_enriched(title="A", overall=85, map_fit=42))
    assert "резюме 85% · карта 42%" in card.text


def test_band_from_presentation() -> None:
    for overall in (90, 75, 50):
        card = build_card(_enriched(title="A", overall=overall))
        assert card.band == badge_band(overall)


def test_verdict_line_uses_presentation_label() -> None:
    card = build_card(
        _enriched(title="A", overall=85, verdict_type="stretch", summary="дотянись")
    )
    label = verdict_style("stretch", overall=85).label
    assert f"{label}: дотянись" in card.text


def test_low_overall_verdict_falls_back_to_borderline() -> None:
    # overall ниже янтарной зоны → «на грани» независимо от типа
    card = build_card(_enriched(title="A", overall=50, verdict_type="precise_fit"))
    borderline = verdict_style("precise_fit", overall=50).label
    assert borderline in card.text


def test_gap_line_picks_critical_first() -> None:
    card = build_card(
        _enriched(title="A", overall=85, critical=["нет лида"]),
    )
    assert "Гэп: нет лида" in card.text


def test_open_button_uses_link_or_contact() -> None:
    card = build_card(_enriched(title="A", overall=85, link="@hr"))
    open_btns = [b for b in card.buttons if b.kind == "open"]
    assert len(open_btns) == 1
    assert open_btns[0].value == "@hr"


def test_open_button_falls_back_to_url() -> None:
    card = build_card(
        _enriched(title="A", overall=85, link=None, url="https://t.me/jobs/9")
    )
    open_btns = [b for b in card.buttons if b.kind == "open"]
    assert open_btns[0].value == "https://t.me/jobs/9"


def test_cover_button_only_above_threshold() -> None:
    above = build_card(
        _enriched(title="A", overall=85, cover_letter="Письмо"),
        cover_letter_threshold=70,
    )
    assert "cover" in _kinds(above)

    below = build_card(
        _enriched(title="B", overall=65, cover_letter="Письмо"),
        cover_letter_threshold=70,
    )
    assert "cover" not in _kinds(below)


def test_cover_button_absent_without_letter() -> None:
    card = build_card(
        _enriched(title="A", overall=85, cover_letter=None),
        cover_letter_threshold=70,
    )
    assert "cover" not in _kinds(card)


def test_contact_button_only_with_contacts() -> None:
    contacts = ContactResult(
        candidates=[ContactCandidate(name="Иван", role="CTO")],
        draft_message="Здравствуйте!",
    )
    with_contacts = build_card(
        _enriched(title="A", overall=85, contacts=contacts)
    )
    contact_btns = [b for b in with_contacts.buttons if b.kind == "contact"]
    assert len(contact_btns) == 1
    assert contact_btns[0].value == "Здравствуйте!"

    without = build_card(_enriched(title="B", overall=85, contacts=None))
    assert "contact" not in _kinds(without)


def test_render_digest_sorts_and_limits() -> None:
    results = [
        _enriched(title="low", overall=60),
        _enriched(title="high", overall=95),
        _enriched(title="mid", overall=80),
    ]
    cards = render_digest(results, top_k=2)
    headers = [c.text.splitlines()[0] for c in cards]
    assert headers == ["high @ Acme", "mid @ Acme"]


def test_send_digest_only_to_owner_chat() -> None:
    transport = _FakeTransport()
    results = [
        _enriched(title="high", overall=95),
        _enriched(title="low", overall=60),
    ]
    cards = send_digest(results, transport, owner_chat_id=12345)
    # отправлено ровно в один чат — владельца
    assert {chat for chat, _ in transport.sent} == {12345}
    assert len(transport.sent) == len(cards) == 2
    # порядок по overall убыв.
    assert transport.sent[0][1].text.splitlines()[0] == "high @ Acme"
