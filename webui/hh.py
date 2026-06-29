"""Текст вакансии hh.* через официальный API (для «Поиска контактов»).

hh.ru отдаёт страницу вакансии за анти-ботом и рендерит тело через JS — простой
GET HTML текста не даёт. Зато есть публичный `api.hh.ru/vacancies/{id}` (без
авторизации, нужен лишь внятный `User-Agent`), который отдаёт структурный JSON.
Из ссылки достаём id, собираем текст из `name` + работодатель + очищенный
`description` + ключевые навыки — этого хватает нормализатору, чтобы вытащить
должность и компанию.

Реальный HTTP спрятан за интерфейсом `JsonTransport`; в тестах — фейк, без сети.
Чистые `parse_hh_vacancy_id`/`build_vacancy_text` тестируются напрямую. Функция
`fetch_hh_vacancy_text` НЕ бросает: не-hh ссылка, сетевой сбой или пустой ответ →
`None`, чтобы вызывающий мягко упал на обычный загрузчик/PDF.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "parse_hh_vacancy_id",
    "build_vacancy_text",
    "fetch_hh_vacancy_text",
    "HH_API_USER_AGENT",
    "JsonTransport",
]

# Хосты hh в разных странах: hh.ru / hh.kz / hh.by / hh.uz и поддомены (spb.hh.ru).
_HH_HOST_RE = re.compile(r"(?:^|\.)hh\.(?:ru|kz|by|uz)$", re.IGNORECASE)
_VACANCY_ID_RE = re.compile(r"/vacancy/(\d+)")

#: hh просит идентифицирующий User-Agent; без внятного UA чаще отдаёт 403.
HH_API_USER_AGENT = "JobAgent/1.0 (https://github.com/Nivanov129/job_finder_agent)"

#: (url, headers) -> распарсенный JSON-ответ.
JsonTransport = Callable[[str, dict[str, str]], dict[str, Any]]


def parse_hh_vacancy_id(url: str) -> str | None:
    """Достать id вакансии из ссылки hh.* (иначе `None`).

    Поддерживает поддомены (`spb.hh.ru`) и query (`?from=...`). Ссылки поиска/
    списка (`hh.ru/search/...`) без `/vacancy/{id}` → `None`.
    """
    try:
        parsed = urlparse(url if "://" in url else "https://" + url)
    except ValueError:
        return None
    if not _HH_HOST_RE.search(parsed.hostname or ""):
        return None
    match = _VACANCY_ID_RE.search(parsed.path)
    return match.group(1) if match else None


def _strip_html(raw: str) -> str:
    """Убрать теги/скрипты и распаковать html-сущности → плоский текст."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def build_vacancy_text(data: dict[str, Any]) -> str:
    """Собрать текст вакансии из JSON hh API (name + компания + описание + навыки)."""
    name = (data.get("name") or "").strip()
    employer = ((data.get("employer") or {}) if isinstance(data.get("employer"), dict) else {})
    company = (employer.get("name") or "").strip()
    desc = _strip_html(data.get("description") or "")
    skills = ", ".join(
        (s.get("name") or "").strip()
        for s in (data.get("key_skills") or [])
        if isinstance(s, dict) and (s.get("name") or "").strip()
    )
    parts: list[str] = []
    if name:
        parts.append(name)
    if company:
        parts.append(f"Компания: {company}")
    if desc:
        parts.append(desc)
    if skills:
        parts.append(f"Ключевые навыки: {skills}")
    return "\n".join(parts).strip()


def fetch_hh_vacancy_text(
    url: str, *, transport: JsonTransport | None = None
) -> str | None:
    """Текст вакансии hh.* через официальный API; `None`, если не hh / не вышло.

    Намеренно проглатывает ошибки (не-hh ссылка, сеть/403, пустой ответ) и
    возвращает `None` — вызывающий мягко падает на `_fetch_url_text`/PDF.
    """
    vacancy_id = parse_hh_vacancy_id(url)
    if not vacancy_id:
        return None
    fetch = transport or _httpx_json
    try:
        data = fetch(
            f"https://api.hh.ru/vacancies/{vacancy_id}",
            {"User-Agent": HH_API_USER_AGENT, "Accept": "application/json"},
        )
    except Exception:  # сеть/403/таймаут — мягкий фолбэк
        return None
    if not isinstance(data, dict):
        return None
    return build_vacancy_text(data) or None


def _httpx_json(  # pragma: no cover - реальная сеть
    url: str, headers: dict[str, str]
) -> dict[str, Any]:
    import httpx

    response = httpx.get(url, headers=headers, timeout=20.0, follow_redirects=True)
    response.raise_for_status()
    return response.json()
