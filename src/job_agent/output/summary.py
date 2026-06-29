"""Компактный вид обогащённого результата (карточка подборки) — общий шейпер.

Используют и web-UI (лента/грид прогона), и MCP (`list_matches`), и локальная БД
подборки (`matchstore`) — одна форма, чтобы данные были консистентны. Цвет-бейдж
берём из `presentation` (единый источник). Чистая функция, тестируется без сети.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..models import EnrichedResult

__all__ = ["match_dict"]


def match_dict(er: EnrichedResult) -> dict[str, Any]:
    """Обогащённый результат → компактный dict для UI/БД/MCP."""
    from ..presentation import badge_band

    s = er.score.scores
    v = er.score.verdict
    gaps = er.score.gaps
    gap = ""
    for items in (gaps.critical, gaps.strategic, gaps.cosmetic):
        if items:
            gap = items[0]
            break
    investigation = None
    inv = getattr(er, "investigation", None)
    if inv is not None and inv.contacts:
        investigation = [
            {
                "name": c.name,
                "role": c.role,
                "route": c.contact_route,
                "confidence": int(c.confidence),
                "grade": c.evidence_grade,
                "link": c.link,
            }
            for c in inv.contacts[:5]
        ]
    return {
        "role": er.vacancy.title,
        "company": er.vacancy.company or "",
        "track": er.score.track,
        "resume": int(s.overall),
        "map": int(s.map_fit),
        "band": badge_band(s.overall),
        "verdict": v.type,
        "verdict_summary": v.summary or "",
        "gap": gap,
        "has_cover": bool(er.cover_letter),
        "link": er.vacancy.link_or_contact or er.vacancy.url or "",
        "investigation": investigation,
    }
