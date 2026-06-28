"""Контакт-ассист (стадия 6, опц.): кандидаты на контакт + черновик обращения.

Включается только при `enable_contacts=true`. Рендерит `prompts/contact-search.md`,
прогоняет булевые запросы через настроенный web-поиск (`Searcher`), подмешивает
выдачу в промт как заземление (движок не выдумывает контакты — берёт из выдачи),
зовёт AI-движок и парсит строгий JSON в `ContactResult`. **Отправки нет** — только
данные и текст черновика. Контракт промта (`prompts/contact-search.md`) read-only,
поэтому выдача дописывается отдельной секцией, а не через плейсхолдер.

Устойчивость: кривой/неполный JSON → `None`, стадия не падает на одной вакансии.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from ..engines.base import Engine
from ..models import ContactResult, Vacancy
from ..websearch.base import Searcher, SearchResult

__all__ = [
    "build_queries",
    "render_prompt",
    "parse_contact_result",
    "find_contacts",
]

_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "contact-search.md"


def build_queries(role: str, company: str, region: str = "") -> list[str]:
    """Булевые `site:`-запросы под linkedin / habr.career / telegram / общий.

    Строятся из роли и компании (см. этап 2 промта). Пустая компания → запросов
    нет (без неё поиск контакта бессмысленен).
    """
    company = company.strip()
    role = role.strip()
    if not company:
        return []
    region_suffix = f" {region.strip()}" if region.strip() else ""
    return [
        f"site:linkedin.com {company} {role} рекрутер{region_suffix}".strip(),
        f"site:habr.career {company} {role}".strip(),
        f"site:t.me {company} вакансия {role}".strip(),
        f"{company} {role} hr контакт{region_suffix}".strip(),
    ]


def _run_searches(
    searcher: Searcher,
    queries: Sequence[str],
    *,
    max_results: int,
) -> list[SearchResult]:
    """Прогнать запросы, собрать выдачу, отбросить дубли по url (порядок сохранён)."""
    seen: set[str] = set()
    out: list[SearchResult] = []
    for query in queries:
        for result in searcher.search(query, max_results=max_results):
            key = result.url or f"{result.title}|{result.snippet}"
            if key in seen:
                continue
            seen.add(key)
            out.append(result)
    return out


def _grounding(queries: Sequence[str], results: Sequence[SearchResult]) -> str:
    """Секция заземления: использованные запросы + найденная выдача для промта."""
    lines = ["", "## Результаты web-поиска (используй только их, контакты не выдумывай)", ""]
    lines.append("Булевые запросы (queries_used):")
    lines.extend(f"- {q}" for q in queries)
    lines.append("")
    if results:
        lines.append("Выдача:")
        for r in results:
            snippet = f" — {r.snippet}" if r.snippet else ""
            lines.append(f"- {r.title} <{r.url}>{snippet}")
    else:
        lines.append("Выдача пуста — используй fallback_paths, candidates оставь пустым.")
    return "\n".join(lines)


def render_prompt(
    vacancy: Vacancy,
    *,
    track_name: str,
    region: str = "",
    output_lang: str = "ru",
) -> str:
    """Подставить данные вакансии и трека в шаблон `prompts/contact-search.md`."""
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    vacancy_link = vacancy.url or vacancy.link_or_contact or ""
    return (
        template.replace("{{role}}", vacancy.title)
        .replace("{{company_name}}", vacancy.company or "")
        .replace("{{region}}", region)
        .replace("{{vacancy_link}}", vacancy_link)
        .replace("{{track_name}}", track_name)
        .replace("{{output_lang}}", output_lang)
    )


def _strip_fences(text: str) -> str:
    """Снять markdown-обёртку ```json ... ``` если она есть."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_object(text: str) -> object | None:
    """Вытащить JSON-объект из текста, терпимо к преамбуле вокруг него."""
    candidate = _strip_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None


def parse_contact_result(text: str) -> ContactResult | None:
    """Распарсить ответ движка в `ContactResult`; мусор/неполнота → `None`."""
    data = _extract_object(text)
    if not isinstance(data, dict):
        return None
    try:
        return ContactResult.model_validate(data)
    except Exception:
        return None


def find_contacts(
    vacancy: Vacancy,
    engine: Engine,
    searcher: Searcher,
    *,
    track_name: str,
    enable_contacts: bool,
    region: str = "",
    output_lang: str = "ru",
    max_results: int = 5,
) -> ContactResult | None:
    """Найти кандидатов на контакт + черновик; выключено/мусор/без компании → `None`.

    Гейт — `enable_contacts` (см. промт, дефолт выкл). Сначала прогоняем булевые
    запросы через `searcher` (этап 2 промта), подмешиваем выдачу в промт, затем
    зовём движок — он уже не ходит в web сам (`web_search=False`), а работает по
    собранной выдаче. Никакой отправки.
    """
    if not enable_contacts:
        return None
    queries = build_queries(vacancy.title, vacancy.company or "", region)
    if not queries:
        return None
    results = _run_searches(searcher, queries, max_results=max_results)
    prompt = render_prompt(
        vacancy,
        track_name=track_name,
        region=region,
        output_lang=output_lang,
    )
    prompt = prompt + "\n" + _grounding(queries, results)
    response = engine.complete(prompt)
    return parse_contact_result(response)
