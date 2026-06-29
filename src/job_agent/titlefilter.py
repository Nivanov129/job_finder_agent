"""Грубый фильтр постов по названию должности (ДО нормализации).

Из резюме AI выводит возможные НАЗВАНИЯ ДОЛЖНОСТЕЙ (рус+англ синонимы); посты, в
тексте которых нет ни одного из этих названий, отсекаются — чтобы не гонять
дорогую AI-нормализацию по заведомо нерелевантным постам. Фильтр грубый и щадящий
(точная фильтрация — позже эмбеддингами). AI-вызов спрятан за интерфейсом `Engine`;
чистые `parse_titles`/`filter_posts_by_titles` тестируются без сети.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from .engines.base import Engine
from .models import RawPost

__all__ = ["derive_titles", "filter_posts_by_titles", "parse_titles", "build_prompt"]

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def _words(text: str) -> list[str]:
    """Значимые слова (≥4 символов) в нижнем регистре — для пословного матча."""
    return [w for w in _WORD_RE.findall(text.lower()) if len(w) >= 4]


def _stem_match(a: str, b: str) -> bool:
    """Слова «совпадают», если одно — префикс другого или общий префикс ≥5.

    Устойчиво к окончаниям/языку: «менеджер»↔«менеджеру», «manager»↔«managers».
    """
    if a == b or a.startswith(b) or b.startswith(a):
        return True
    common = 0
    for ca, cb in zip(a, b, strict=False):
        if ca != cb:
            break
        common += 1
    return common >= 5

_TEMPLATE = (
    "Вот резюме кандидата. Выведи 10–15 КОРОТКИХ названий должности (1–3 слова), "
    "которые встречаются в ЗАГОЛОВКАХ подходящих вакансий — базовые формы и "
    "ключевые слова, на русском И английском (напр. «Product Manager», "
    "«Продакт-менеджер», «Менеджер продукта», «Head of Product», «Руководитель "
    "продукта», «Product Owner»). БЕЗ уточнений Senior/Junior/Mobile/AI и без "
    "перечисления стека — только базовые названия роли. Только JSON-массив строк, "
    "без пояснений.\n\nРезюме:\n{resume}\n\nФормат: [\"...\", \"...\"]"
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
    """Оставить посты, чей текст несёт какое-то из названий ролей — ПОСЛОВНО.

    Раньше матчили точную подстроку названия, и русские формулировки терялись:
    «Продакт-менеджер» не ловил «продакт менеджер» (пробел) / «продуктовый
    менеджер» / «менеджер по продукту». Теперь пост проходит, если для какого-то
    названия ВСЕ его значимые слова (≥4 симв.) встречаются в тексте по стему —
    устойчиво к дефису/пробелу, порядку слов, предлогам и окончаниям. Фильтр
    грубый и щадящий (точную фильтрацию делают гейт ролей и скоринг дальше).

    Пустой список названий → ничего не фильтруем.
    """
    posts = list(posts)
    if not titles:
        return posts
    # Каждое название → набор значимых слов; пустые (короткие) отбрасываем.
    title_words = [ws for t in titles if (ws := _words(t))]
    if not title_words:
        return posts
    out: list[RawPost] = []
    for post in posts:
        post_words = _words(post.raw_text)
        if post_words and any(
            all(any(_stem_match(rw, pw) for pw in post_words) for rw in ws)
            for ws in title_words
        ):
            out.append(post)
    return out
