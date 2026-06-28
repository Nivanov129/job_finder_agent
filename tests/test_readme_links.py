"""Лёгкая проверка README: внутренние ссылки/пути не битые.

Сканирует markdown-ссылки вида `[текст](путь)` в README.md, отбрасывает
внешние (http/https/mailto/tg-юзернеймы) и якоря, и проверяет, что каждый
локальный путь существует относительно корня репозитория. Ловит опечатки в
путях к файлам (config.schema.json, prompts/, design/, compose.yml и т.п.).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

# [текст](цель) — нежадно, без вложенных скобок в цели.
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

# Внешние схемы, которые не проверяем на наличие файла.
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tg://")


def _local_targets() -> list[str]:
    text = README.read_text(encoding="utf-8")
    targets: list[str] = []
    for raw in LINK_RE.findall(text):
        target = raw.strip()
        if target.startswith(EXTERNAL_PREFIXES) or target.startswith("#"):
            continue
        # отрезаем якорь у локальной ссылки (file.md#section)
        targets.append(target.split("#", 1)[0])
    return targets


def test_readme_exists():
    assert README.is_file()


def test_readme_has_local_links():
    # защита от «тест ничего не проверяет», если регэксп/формат поедет
    assert _local_targets(), "в README не нашлось ни одной локальной ссылки"


def test_readme_local_links_resolve():
    missing = [t for t in _local_targets() if not (REPO_ROOT / t).exists()]
    assert not missing, f"битые внутренние ссылки в README: {missing}"
