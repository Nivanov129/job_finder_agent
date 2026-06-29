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
from collections.abc import Sequence
from datetime import datetime

from ..models import RawPost
from ..websearch.base import Searcher
from .base import Collector

__all__ = ["LinkedinSearchCollector", "build_dork", "DEFAULT_DOMAINS"]

DEFAULT_DOMAINS = ("ru.linkedin.com", "www.linkedin.com")
_MAX_ROLES = 8  # ограничиваем число запросов к web-поиску за прогон

_logger = logging.getLogger("job_agent.collectors.linkedin")


def build_dork(role: str, domains: Sequence[str]) -> str:
    """Собрать дорк под одну роль и список доменов LinkedIn."""
    sites = " OR ".join(f"site:{d.strip('/')}/" for d in domains if d.strip())
    return f'"{role.strip()}" "Vacancy" -intitle:"vacancies" {sites}'.strip()


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
        out: list[RawPost] = []
        seen_urls: set[str] = set()
        for role in self._roles:
            query = build_dork(role, self._domains)
            try:
                results = self._searcher.search(query, max_results=self._max_results)
            except Exception as exc:  # web-поиск недоступен/упал на одной роли
                _logger.warning("LinkedIn-роль «%s» пропущена: %s", role, exc)
                continue
            for res in results:
                url = res.url or ""
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                text = "\n".join(p for p in (res.title, res.snippet) if p).strip()
                if text:
                    out.append(
                        RawPost(raw_text=text, source="linkedin", url=url or None)
                    )
        return out
