"""Коллектор агрегатора getmatch.ru (JSON API листинга вакансий).

В отличие от vseti, getmatch отдаёт структурированный JSON — парсим его, а не
вёрстку. Хрупкость формата изолирована в чистой функции `parse_getmatch_json`;
сетевой доступ инкапсулирован в `JsonFetcher`, в тестах подменяется фейком
(юнит-тесты в сеть не ходят). Битый/неожиданный JSON → пустой результат, не падаем.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

from ..models import RawPost
from .base import Collector

__all__ = ["GetmatchCollector", "parse_getmatch_json", "JsonFetcher", "DEFAULT_URL"]

# url -> сырой текст ответа (JSON). Дефолт ходит в сеть; в тестах фейк.
JsonFetcher = Callable[[str], str]

DEFAULT_URL = "https://getmatch.ru/api/web/v1/vacancies"
_VACANCY_BASE = "https://getmatch.ru/vacancies"


def _http_fetch(url: str) -> str:  # pragma: no cover - реальная сеть, не в юнит-тестах
    import httpx

    resp = httpx.get(
        url,
        timeout=30.0,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (job-agent)",
            "Accept": "application/json",
        },
    )
    resp.raise_for_status()
    return resp.text


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _company_name(item: dict) -> str | None:
    company = item.get("company")
    if isinstance(company, dict):
        name = company.get("name")
        return name if isinstance(name, str) else None
    if isinstance(company, str):
        return company
    return None


def _salary(item: dict) -> str | None:
    """Собрать строку зарплаты из разных возможных полей."""
    salary = item.get("salary")
    if isinstance(salary, str):
        return salary.strip() or None
    parts: list[str] = []
    lo = item.get("salary_from")
    hi = item.get("salary_to")
    cur = item.get("salary_currency") or ""
    if lo:
        parts.append(f"от {lo}")
    if hi:
        parts.append(f"до {hi}")
    if not parts:
        return None
    line = " ".join(parts)
    return f"{line} {cur}".strip() if cur else line


def _url(item: dict) -> str | None:
    slug = item.get("slug")
    if isinstance(slug, str) and slug:
        return f"{_VACANCY_BASE}/{slug}"
    vid = item.get("id")
    if vid is not None:
        return f"{_VACANCY_BASE}/{vid}"
    return None


def _date(item: dict) -> datetime | None:
    for key in ("published_at", "created_at", "date"):
        value = item.get(key)
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def parse_getmatch_json(text: str) -> list[RawPost]:
    """Распарсить JSON-ответ getmatch в список постов.

    Поддерживает как `{"vacancies": [...]}`, так и голый список. Записи без
    заголовка пропускаются. `raw_text` собирается из заголовка, компании,
    зарплаты и описания. Невалидный JSON → пустой список.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []

    if isinstance(data, dict):
        items = data.get("vacancies") or data.get("items") or data.get("results") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []

    posts: list[RawPost] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("name") or item.get("position")
        if not isinstance(title, str) or not title.strip():
            continue

        lines = [title.strip()]
        company = _company_name(item)
        if company:
            lines.append(company)
        salary = _salary(item)
        if salary:
            lines.append(salary)
        desc = item.get("description") or item.get("short_description") or ""
        if isinstance(desc, str) and desc.strip():
            lines.append(desc.strip())

        posts.append(
            RawPost(
                raw_text="\n".join(lines),
                source="getmatch",
                url=_url(item),
                date=_date(item),
            )
        )
    return posts


class GetmatchCollector(Collector):
    """Сбор вакансий из JSON-API getmatch.ru."""

    def __init__(self, url: str = DEFAULT_URL, fetcher: JsonFetcher | None = None) -> None:
        self._url = url
        self._fetch_json: JsonFetcher = fetcher or _http_fetch

    def fetch(self, since: datetime) -> list[RawPost]:
        since_aware = _as_aware(since)
        text = self._fetch_json(self._url)
        out: list[RawPost] = []
        for post in parse_getmatch_json(text):
            if post.date is not None and _as_aware(post.date) < since_aware:
                continue
            out.append(post)
        return out
