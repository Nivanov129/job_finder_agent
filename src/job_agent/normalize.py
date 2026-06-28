"""Нормализация (стадия 2): сырой пост → строгий JSON → `list[Vacancy]`.

Рендерит `prompts/normalize.md`, зовёт AI-движок, парсит строгий JSON-массив
в нормализованные вакансии. Устойчиво к мусору: преамбула вокруг JSON,
markdown-обёртка, не-вакансия → пустой список, а не исключение. Провенанс
(`source/url/date`) дописывается из исходного `RawPost` — поля скоринга он не
выдумывает. Контракт промта (`prompts/normalize.md`) read-only, не переписываем.
"""

from __future__ import annotations

import json
from pathlib import Path

from .engines.base import Engine
from .models import RawPost, Vacancy

__all__ = ["normalize_post", "normalize_posts", "parse_vacancies", "render_prompt"]

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "normalize.md"


def render_prompt(post: RawPost, *, output_lang: str = "ru") -> str:
    """Подставить данные поста в шаблон `prompts/normalize.md`."""
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{{raw_text}}", post.raw_text)
        .replace("{{source}}", post.source)
        .replace("{{output_lang}}", output_lang)
    )


def _strip_fences(text: str) -> str:
    """Убрать markdown-обёртку ```json ... ``` если она есть."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    # отбросить открывающую (```json / ```) и закрывающую (```) строки
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_array(text: str) -> object | None:
    """Вытащить JSON-массив из текста, терпимо к преамбуле вокруг него."""
    candidate = _strip_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # запасной путь: первый '[' .. последний ']'
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None


def parse_vacancies(text: str, post: RawPost) -> list[Vacancy]:
    """Распарсить ответ движка в `list[Vacancy]`, дописав провенанс из поста.

    Записи без непустого `title` пропускаются. Любой нечитаемый/неожиданный
    ответ (не массив объектов) → пустой список — стадия не падает на мусоре.
    """
    data = _extract_array(text)
    if not isinstance(data, list):
        return []

    out: list[Vacancy] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        out.append(
            Vacancy(
                title=title.strip(),
                company=_opt_str(item.get("company")),
                link_or_contact=_opt_str(item.get("link_or_contact")),
                salary=_opt_str(item.get("salary")),
                description=_str(item.get("description")),
                source=post.source,
                url=post.url,
                date=post.date,
            )
        )
    return out


def _opt_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize_post(
    post: RawPost, engine: Engine, *, output_lang: str = "ru"
) -> list[Vacancy]:
    """Нормализовать один пост через движок в `list[Vacancy]`."""
    prompt = render_prompt(post, output_lang=output_lang)
    response = engine.complete(prompt)
    return parse_vacancies(response, post)


def normalize_posts(
    posts: list[RawPost], engine: Engine, *, output_lang: str = "ru"
) -> list[Vacancy]:
    """Нормализовать набор постов; вакансии всех постов в одном списке."""
    out: list[Vacancy] = []
    for post in posts:
        out.extend(normalize_post(post, engine, output_lang=output_lang))
    return out
