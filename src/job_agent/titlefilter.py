"""Грубый фильтр постов по названию должности (ДО нормализации).

Из резюме AI выводит возможные НАЗВАНИЯ ДОЛЖНОСТЕЙ (рус+англ синонимы); посты, в
тексте которых нет ни одного из этих названий, отсекаются — чтобы не гонять
дорогую AI-нормализацию по заведомо нерелевантным постам. Фильтр грубый и щадящий
(точная фильтрация — позже эмбеддингами). AI-вызов спрятан за интерфейсом `Engine`;
чистые `parse_titles`/`filter_posts_by_titles` тестируются без сети.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from .engines.base import Engine
from .models import RawPost

__all__ = ["derive_titles", "filter_posts_by_titles", "parse_titles", "build_prompt"]

_TEMPLATE = (
    "Вот резюме кандидата. Выведи 12–20 возможных НАЗВАНИЙ ДОЛЖНОСТЕЙ, на которые он "
    "подходит — конкретные, как пишут в вакансиях, с синонимами на русском И "
    "английском (напр. «Product Manager», «Продакт-менеджер», «Head of Product», "
    "«Руководитель продукта»). Не общие слова, а названия ролей. Только JSON-массив "
    "строк, без пояснений.\n\nРезюме:\n{resume}\n\nФормат: [\"...\", \"...\"]"
)


def build_prompt(resume_text: str) -> str:
    return _TEMPLATE.format(resume=resume_text[:6000])


def parse_titles(text: str) -> list[str]:
    """Достать JSON-массив названий из ответа движка (терпимо к обёртке)."""
    s = text.strip()
    start, end = s.find("["), s.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    # отбрасываем слишком короткие (≤3) — они дают ложные совпадения подстрокой
    return [str(x).strip() for x in data if len(str(x).strip()) >= 4]


def derive_titles(engine: Engine, resume_text: str) -> list[str]:
    """Названия должностей из резюме (один AI-вызов). Пустое резюме → пусто."""
    if not resume_text.strip():
        return []
    return parse_titles(engine.complete(build_prompt(resume_text)))


def filter_posts_by_titles(
    posts: Iterable[RawPost], titles: list[str]
) -> list[RawPost]:
    """Оставить посты, в тексте которых есть хотя бы одно название (без учёта регистра).

    Пустой список названий → ничего не фильтруем (возвращаем всё как есть).
    """
    posts = list(posts)
    if not titles:
        return posts
    lowered = [t.lower() for t in titles]
    return [p for p in posts if any(t in p.raw_text.lower() for t in lowered)]
