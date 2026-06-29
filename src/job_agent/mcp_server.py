"""MCP-сервер (stdio): инструменты job-agent для локального агента (Claude
Desktop/Code). Читает тот же каталог данных, что и web-UI (`data/`): `config.json`,
`.env` (ключи движка), `results.json` (подборка последнего прогона).

Инструменты:
- ``list_matches`` — вакансии из последнего прогона (читает `results.json`,
  который пишут и web-UI, и ``run_backfill``);
- ``run_backfill`` — запустить подбор за период и вернуть финалистов;
- ``find_contacts`` — контакты к вакансии по ссылке / тексту / паре роль+компания.

Запуск: ``uv run job-agent-mcp`` (каталог данных — переменная ``JOB_AGENT_DATA``
или ``./data`` относительно текущей папки).

Доменные функции (``load_matches``/``run_search``/``contacts_for``) отделены от
MCP-рантайма и тестируются без сети (движок и web-поиск инъектируются). ``main``
лишь регистрирует их как MCP-инструменты и поднимает stdio-сервер. Модуль не
зависит от web-UI — только от ядра ``job_agent`` (чтобы не тащить FastAPI).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .engines import Engine
    from .models import EnrichedResult
    from .websearch.base import Searcher

__all__ = ["main", "load_matches", "run_search", "contacts_for", "match_dict", "data_dir"]


def data_dir() -> Path:
    """Каталог данных: `JOB_AGENT_DATA` или `./data` (тот же, что у web-UI)."""
    return Path(os.environ.get("JOB_AGENT_DATA", "data")).resolve()


def _load_env(base: Path) -> None:
    """Подмешать ключи из `data/.env` в окружение (движок читает их оттуда).

    `setdefault` — реальное окружение приоритетнее файла; пустых/комментариев нет.
    """
    env_file = base / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key:
            os.environ.setdefault(key, val.strip().strip("'\""))


def match_dict(er: EnrichedResult) -> dict[str, Any]:
    """Компактный вид вакансии для агента (роль, компания, проценты, вердикт)."""
    from .presentation import badge_band

    s = er.score.scores
    return {
        "role": er.vacancy.title,
        "company": er.vacancy.company or "",
        "track": er.score.track,
        "resume": int(s.overall),
        "map": int(s.map_fit),
        "band": badge_band(s.overall),
        "verdict": er.score.verdict.type,
        "verdict_summary": er.score.verdict.summary or "",
        "link": er.vacancy.link_or_contact or er.vacancy.url or "",
    }


def load_matches(base: Path | None = None) -> list[dict[str, Any]]:
    """Вакансии из последнего прогона (`results.json`) или `[]`, если прогонов нет."""
    base = Path(base) if base is not None else data_dir()
    path = base / "results.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def run_search(
    base: Path | None = None,
    *,
    days: int | None = None,
    engine: Engine | None = None,
    searcher: Searcher | None = None,
) -> dict[str, Any]:
    """Запустить подбор за период (one-shot), записать `results.json`, вернуть итог.

    `days` — глубина в днях (None/0 → `config.backfill_days`). `engine`/`searcher`
    инъектируются в тестах; в бою строятся из конфига.
    """
    from datetime import UTC, datetime, timedelta

    from .config import load_config
    from .dedup import SeenStore
    from .pipeline import run_pipeline

    base = Path(base) if base is not None else data_dir()
    _load_env(base)
    config = load_config(base / "config.json")
    window = days if days and days > 0 else config.backfill_days
    since = datetime.now(UTC) - timedelta(days=window)
    matches: list[dict[str, Any]] = []
    run_pipeline(
        config,
        since=since,
        base_dir=base,
        output_path=base / "backfill.xlsx",
        seen_store=SeenStore(":memory:"),
        engine=engine,
        searcher=searcher,
        on_result=lambda er: matches.append(match_dict(er)),
    )
    try:
        tmp = base / "results.json.tmp"
        tmp.write_text(json.dumps(matches, ensure_ascii=False), encoding="utf-8")
        tmp.replace(base / "results.json")
    except OSError:
        pass
    return {"count": len(matches), "matches": matches}


def _fetch_text(url: str) -> str:
    """Грубо вытащить текст со страницы вакансии (без тегов/скриптов)."""
    import httpx

    resp = httpx.get(
        url, follow_redirects=True, timeout=20.0,
        headers={"User-Agent": "Mozilla/5.0 (job-agent-mcp)"},
    )
    resp.raise_for_status()
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", resp.text)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()


def contacts_for(
    base: Path | None = None,
    *,
    link: str = "",
    text: str = "",
    role: str = "",
    company: str = "",
    engine: Engine | None = None,
    searcher: Searcher | None = None,
) -> dict[str, Any]:
    """Контакты к вакансии: по `role`+`company`, по `text` или по `link`.

    Возвращает `{role, company, contacts}` или `{error}`. Для hh.ru ссылка часто
    за анти-ботом — надёжнее передать `text` или `role`+`company`.
    """
    from .config import load_config
    from .engines import make_engine
    from .enrich.contacts import find_contacts
    from .models import RawPost, Vacancy
    from .normalize import normalize_post
    from .websearch import make_searcher

    base = Path(base) if base is not None else data_dir()
    _load_env(base)
    config = load_config(base / "config.json")
    engine = engine or make_engine(config)
    if role and company:
        vac = Vacancy(
            title=role, company=company,
            link_or_contact=link or None, url=link or None,
        )
    else:
        body = text.strip() or (_fetch_text(link) if link else "")
        if not body:
            return {"error": "дай link, text или role+company"}
        vacs = normalize_post(
            RawPost(raw_text=body[:8000], source="mcp", url=link or None),
            engine, output_lang=config.output_lang,
        )
        if not vacs:
            return {"error": "не распознал вакансию в тексте"}
        vac = vacs[0]
        if link and not vac.url:
            vac = vac.model_copy(update={"url": link})
    search = searcher or make_searcher(config)
    res = find_contacts(
        vac, engine, search, track_name=vac.title,
        enable_contacts=True, output_lang=config.output_lang,
    )
    return {
        "role": vac.title,
        "company": vac.company or "",
        "contacts": res.model_dump() if res is not None else None,
    }


def main() -> None:  # pragma: no cover - stdio MCP рантайм
    """Поднять stdio MCP-сервер с инструментами job-agent."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("job-agent")

    @server.tool()
    def list_matches() -> list[dict[str, Any]]:
        """Вакансии из последнего прогона (подборка) с процентами и вердиктом."""
        return load_matches()

    @server.tool()
    def run_backfill(days: int = 0) -> dict[str, Any]:
        """Запустить подбор вакансий за период (days дней; 0 — как в конфиге)."""
        return run_search(days=days or None)

    @server.tool()
    def find_contacts(
        link: str = "", text: str = "", role: str = "", company: str = ""
    ) -> dict[str, Any]:
        """Найти контакты к вакансии по ссылке, тексту или паре роль+компания."""
        return contacts_for(link=link, text=text, role=role, company=company)

    server.run()


if __name__ == "__main__":  # pragma: no cover
    main()
