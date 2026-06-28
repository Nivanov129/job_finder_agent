# Job Agent — образ пайплайна.
# Всё локально: образ только запускает код-пайплайн, внешние вызовы идут к
# выбранному пользователем AI-движку и self-host web-поиску (SearXNG в compose).
FROM python:3.12-slim

# uv — менеджер пакетов проекта.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    # Кэш модели эмбеддингов — общий том, прогревается model-init.
    FASTEMBED_CACHE_PATH=/models \
    # Seen-store по умолчанию в монтируемом томе.
    JOB_AGENT_SEEN_DB=/var/lib/job-agent/job_agent_seen.db

WORKDIR /app

# Сначала только манифесты — слой зависимостей кэшируется отдельно от кода.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Код пакета и read-only контракты (промты, схема, дизайн-токены).
COPY src ./src
COPY prompts ./prompts
COPY config.schema.json ./config.schema.json
# Web-UI (FastAPI). Не отдельный пакет — лежит в /app, импортируется по
# PYTHONPATH=/app сервисом webui (см. compose.yml). Статика/шрифты вшиты внутрь.
COPY webui ./webui
RUN uv sync --frozen --no-dev

# Данные участника (config.json, резюме, шаблоны, карта поиска) монтируются сюда.
WORKDIR /data

ENTRYPOINT ["job-agent"]
# По умолчанию — ночной инкрементальный прогон по встроенному расписанию.
CMD ["nightly", "--config", "/data/config.json", "--out", "/data/job-agent-result.xlsx", "--serve"]
