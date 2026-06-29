"""Доп. источник вакансий: LinkedIn через web-поиск (дорки по ролям).

LinkedIn нельзя скрейпить (login-wall), но публичные job-страницы индексируются.
Гоняем Google-style дорк через настроенный `Searcher` (SearXNG) по каждой роли:

    "<роль>" "Vacancy" -intitle:"vacancies" site:ru.linkedin.com/ OR site:www.linkedin.com/

Выдача (title + snippet) превращается в `RawPost` — дальше обычный пайплайн
(нормализация → гейт → скоринг). Дат у выдачи нет, поэтому по `since` не режем
(дорк и так возвращает актуальное). Источник изолирован: сбой поиска по одной
роли логируется и не валит остальные.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from ..models import RawPost
from ..websearch.base import Searcher
from .base import Collector

__all__ = ["LinkedinSearchCollector", "build_dork", "DEFAULT_DOMAINS"]

DEFAULT_DOMAINS = ("ru.linkedin.com", "www.linkedin.com")
_MAX_ROLES = 8  # ограничиваем число запросов к web-поиску за прогон

_logger = logging.getLogger("job_agent.collectors.linkedin")

# Агрегатные листинги LinkedIn (не конкретные вакансии): .../jobs/<role>-jobs,
# /jobs/search, /jobs/collections — это шум, не вакансия.
_AGG_URL = re.compile(r"/jobs/(search|collections|[^/?#]*-jobs)", re.I)
# Заголовки-листинги вида «140,000+ Product Manager jobs in …».
_AGG_TITLE = re.compile(r"^\s*\d[\d,\s]*\+?\s+.*\bjobs?\b", re.I)
_RU_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "ма": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}


def build_dork(role: str, domains: Sequence[str]) -> str:
    """Собрать дорк под одну роль и список доменов LinkedIn."""
    sites = " OR ".join(f"site:{d.strip('/')}/" for d in domains if d.strip())
    return f'"{role.strip()}" "Vacancy" -intitle:"vacancies" {sites}'.strip()


def _looks_aggregate(url: str, title: str) -> bool:
    """Агрегатная страница-листинг, а не конкретная вакансия → отбрасываем."""
    return bool(_AGG_URL.search(url or "")) or bool(_AGG_TITLE.match(title or ""))


def _parse_date(text: str) -> datetime | None:
    """Достать дату из заголовка/сниппета (ISO или рус. «6 окт. 2025») — для
    отсечения неактуальных. Не нашли — None (пропускаем как есть)."""
    iso = re.search(r"(20\d\d)-(\d{1,2})-(\d{1,2})", text)
    if iso:
        try:
            return datetime(int(iso[1]), int(iso[2]), int(iso[3]), tzinfo=UTC)
        except ValueError:
            pass
    ru = re.search(r"(\d{1,2})\s*([а-яё]{3,})\.?\s*(20\d\d)", text.lower())
    if ru:
        mon = next((v for k, v in _RU_MONTHS.items() if ru[2].startswith(k)), None)
        if mon:
            try:
                return datetime(int(ru[3]), mon, int(ru[1]), tzinfo=UTC)
            except ValueError:
                pass
    return None


class LinkedinSearchCollector(Collector):
    """Сбор постов-вакансий с LinkedIn через дорки в web-поиске.

    `roles` — допустимые роли (из резюме/`role_gate`); по каждой строится дорк.
    `searcher` инъектируется (в тестах — фейк). Дубли режутся по url.
    """

    def __init__(
        self,
        roles: Sequence[str],
        searcher: Searcher,
        *,
        domains: Sequence[str] = DEFAULT_DOMAINS,
        max_results: int = 10,
        max_roles: int = _MAX_ROLES,
    ) -> None:
        # Уникальные непустые роли, не больше max_roles (экономим запросы).
        seen: set[str] = set()
        picked: list[str] = []
        for r in roles:
            key = r.strip().lower()
            if key and key not in seen:
                seen.add(key)
                picked.append(r.strip())
            if len(picked) >= max_roles:
                break
        self._roles = picked
        self._searcher = searcher
        self._domains = tuple(domains)
        self._max_results = max_results

    def fetch(self, since: datetime) -> list[RawPost]:
        since_aware = since if since.tzinfo else since.replace(tzinfo=UTC)
        out: list[RawPost] = []
        seen_urls: set[str] = set()
        dropped = {"agg": 0, "stale": 0}
        for role in self._roles:
            query = build_dork(role, self._domains)
            try:
                results = self._searcher.search(query, max_results=self._max_results)
            except Exception as exc:  # web-поиск недоступен/упал на одной роли
                _logger.warning("LinkedIn-роль «%s» пропущена: %s", role, exc)
                continue
            for res in results:
                url = res.url or ""
                title = res.title or ""
                if url and url in seen_urls:
                    continue
                # отсекаем агрегатные листинги (не конкретные вакансии)
                if _looks_aggregate(url, title):
                    dropped["agg"] += 1
                    continue
                if url:
                    seen_urls.add(url)
                text = "\n".join(p for p in (title, res.snippet) if p).strip()
                if not text:
                    continue
                # отсекаем явно старые (дата в сниппете раньше периода)
                date = _parse_date(text)
                if date is not None and date < since_aware:
                    dropped["stale"] += 1
                    continue
                out.append(
                    RawPost(raw_text=text, source="linkedin", url=url or None, date=date)
                )
        if dropped["agg"] or dropped["stale"]:
            _logger.info(
                "LinkedIn: отброшено листингов %d, устаревших %d; оставлено %d",
                dropped["agg"], dropped["stale"], len(out),
            )
        return out
