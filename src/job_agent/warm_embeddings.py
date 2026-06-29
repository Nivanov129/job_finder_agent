"""Прогрев модели эмбеддингов (сервис `model-init`): качает модель заранее, но
ТОЛЬКО если в конфиге включены эмбеддинги (`use_embeddings`). Иначе локальная
модель не нужна — пропускаем загрузку.

Конфиг может ещё не существовать (до первого `install`) — тогда грузим (дефолт).
Запуск: `python -m job_agent.warm_embeddings`.
"""

from __future__ import annotations

import json
import os


def _embeddings_enabled(config_path: str = "/data/config.json") -> bool:
    if not os.path.exists(config_path):
        return True  # конфига ещё нет — ведём себя по дефолту (эмбеддинги вкл)
    try:
        return bool(json.load(open(config_path, encoding="utf-8")).get("use_embeddings", True))
    except Exception:
        return True


def main() -> None:
    if not _embeddings_enabled():
        print("use_embeddings=false — локальная модель не нужна, загрузку пропускаю")
        return
    from .embeddings import warm_model

    warm_model()


if __name__ == "__main__":
    main()
