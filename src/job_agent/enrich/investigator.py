"""Доп-движок поиска контактов (опц.): инвестигатор по мотивам скилла
recruiting-contact-investigator.

Отличие от `contacts.find_contacts`: не один проход по фикс-запросам, а
расследование — движок (CLI-агент с встроенным web-поиском) сам ведёт ветви
поиска (Telegram/LinkedIn/Habr/сайт/по имени с транслитерацией), оценивает
доказательства и ранжирует контакты с confidence. Выдача идёт ОТДЕЛЬНЫМ полем
`EnrichedResult.investigation` рядом с основной `contacts` — «доп. выдача с именем».

Включается только при `enable_contact_investigator`. Устойчивость: кривой JSON →
`None`, стадия не падает на одной вакансии. Отправки нет — только данные.
"""

from __future__ import annotations

from pathlib import Path

from ..engines.base import Engine
from ..models import ContactInvestigation, Vacancy
from .contacts import _extract_object  # переиспользуем терпимый парсер JSON

__all__ = ["render_prompt", "parse_investigation", "investigate_contacts"]

_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "contact-investigator.md"


def render_prompt(
    vacancy: Vacancy,
    *,
    track_name: str,
    region: str = "",
    output_lang: str = "ru",
) -> str:
    """Подставить данные вакансии в шаблон `prompts/contact-investigator.md`."""
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


def parse_investigation(text: str) -> ContactInvestigation | None:
    """Распарсить ответ движка в `ContactInvestigation`; мусор/неполнота → `None`."""
    data = _extract_object(text)
    if not isinstance(data, dict):
        return None
    try:
        return ContactInvestigation.model_validate(data)
    except Exception:
        return None


def investigate_contacts(
    vacancy: Vacancy,
    engine: Engine,
    *,
    track_name: str,
    enable_investigator: bool,
    region: str = "",
    output_lang: str = "ru",
) -> ContactInvestigation | None:
    """Провести расследование контактов; выключено/без компании/мусор → `None`.

    Движок ведёт web-поиск сам (`web_search=True`) — CLI-агенту это включает
    встроенный браузинг; у API/Ollama флаг трактуется по их правилам.
    """
    if not enable_investigator:
        return None
    if not (vacancy.company or "").strip():
        return None  # без компании расследовать некого
    prompt = render_prompt(
        vacancy, track_name=track_name, region=region, output_lang=output_lang
    )
    response = engine.complete(prompt, web_search=True)
    return parse_investigation(response)
