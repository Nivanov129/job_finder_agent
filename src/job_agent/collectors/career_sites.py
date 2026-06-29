"""Источник вакансий: карьерные сайты компаний через web-поиск (дорки по ролям).

Пользователь задаёт домены своих целевых компаний (напр. `career.ozon.ru`), а
роли берём из резюме (`role_gate` — те же «Допустимые роли»). По каждой роли
гоняем дорк через настроенный `Searcher` (SearXNG), ограничив выдачу доменами:

    "<роль>" (site:career.ozon.ru OR site:yandex.ru/jobs)

Выдача (title + snippet) превращается в `RawPost` — дальше обычный пайплайн
(нормализация → пред-фильтр эмбеддингами → AI-скоринг), который и делает
семантическую часть. Дат у выдачи нет, по `since` не режем. Источник изолирован:
сбой поиска по одной роли логируется и не валит остальные. Число запросов
ограничено (`max_roles`), все домены идут одним запросом на роль.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from urllib.parse import urlparse

from ..models import RawPost
from ..websearch.base import Searcher
from .base import Collector

__all__ = ["CareerSiteCollector", "build_query", "normalize_site"]

_MAX_ROLES = 8  # потолок запросов к web-поиску за прогон
_logger = logging.getLogger("job_agent.collectors.career_sites")


def normalize_site(raw: str) -> str:
    """Привести ввод к `домен[/путь]`: убрать схему, `www.`, хвостовой `/`, пробелы.

    Путь СОХРАНЯЕМ — иначе для карьерных разделов под общим доменом
    (`yandex.ru/jobs`, `tbank.ru/career`) дорк `site:` шерстил бы весь домен
    (почту/банк/поиск), а не вакансии. `https://career.ozon.ru/` → `career.ozon.ru`;
    `https://yandex.ru/jobs` → `yandex.ru/jobs`; пустое/мусор → ``.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "https://" + s
    parsed = urlparse(s)
    host = (parsed.hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    path = (parsed.path or "").rstrip("/")
    return host + path


def build_query(role: str, sites: Sequence[str]) -> str:
    """Дорк под одну роль и список доменов/путей: `"<роль>" (site:a OR site:b)`.

    Без хвостового `/` — чтобы `site:yandex.ru/jobs` ловил и `/jobs`, и
    `/jobs/vacancy/…` (со слешем срезало бы страницу-корень раздела).
    """
    group = " OR ".join(f"site:{d}" for d in sites if d)
    role = role.strip()
    if not group:
        return f'"{role}"'
    return f'"{role}" ({group})'


class CareerSiteCollector(Collector):
    """Сбор вакансий с карьерных сайтов компаний через дорки в web-поиске.

    `roles` — допустимые роли (из резюме/`role_gate`); `sites` — домены компаний
    (нормализуются). `searcher` инъектируется (в тестах — фейк). Без ролей или
    без сайтов — `fetch` отдаёт пусто. Дубли режутся по url.
    """

    def __init__(
        self,
        roles: Sequence[str],
        searcher: Searcher,
        sites: Sequence[str],
        *,
        max_results: int = 10,
        max_roles: int = _MAX_ROLES,
    ) -> None:
        # Уникальные непустые роли, не больше max_roles (экономим запросы).
        seen_roles: set[str] = set()
        picked: list[str] = []
        for r in roles:
            key = r.strip().lower()
            if key and key not in seen_roles:
                seen_roles.add(key)
                picked.append(r.strip())
            if len(picked) >= max_roles:
                break
        self._roles = picked
        self._searcher = searcher
        # Уникальные нормализованные домены (порядок сохраняем).
        seen_sites: set[str] = set()
        self._sites: list[str] = []
        for s in sites:
            dom = normalize_site(s)
            if dom and dom not in seen_sites:
                seen_sites.add(dom)
                self._sites.append(dom)
        self._max_results = max_results

    def fetch(self, since: datetime) -> list[RawPost]:
        del since  # у выдачи поиска дат нет — период не режем
        if not self._roles or not self._sites:
            return []
        out: list[RawPost] = []
        seen_urls: set[str] = set()
        for role in self._roles:
            query = build_query(role, self._sites)
            try:
                results = self._searcher.search(query, max_results=self._max_results)
            except Exception as exc:  # web-поиск упал на одной роли — не валим всё
                _logger.warning("Карьерные сайты, роль «%s» пропущена: %s", role, exc)
                continue
            for res in results:
                url = res.url or ""
                if url and url in seen_urls:
                    continue
                # Отсекаем корень сайта (career.ozon.ru/) — это не конкретная вакансия.
                if url and not (urlparse(url).path or "").strip("/"):
                    continue
                if url:
                    seen_urls.add(url)
                text = "\n".join(p for p in (res.title, res.snippet) if p).strip()
                if not text:
                    continue
                out.append(
                    RawPost(raw_text=text, source="career_site", url=url or None)
                )
        if out:
            _logger.info(
                "Карьерные сайты: %d вакансий с %d сайтов по %d ролям",
                len(out), len(self._sites), len(self._roles),
            )
        return out
