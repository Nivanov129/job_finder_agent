# Job Agent — образ пайплайна.
# Всё локально: образ только запускает код-пайплайн, внешние вызовы идут к
# выбранному пользователем AI-движку и self-host web-поиску (SearXNG в compose).
FROM python:3.12-slim

# uv — менеджер пакетов проекта.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:/root/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    # Кэш модели эмбеддингов — общий том, прогревается model-init.
    FASTEMBED_CACHE_PATH=/models \
    # Seen-store по умолчанию в монтируемом томе.
    JOB_AGENT_SEEN_DB=/var/lib/job-agent/job_agent_seen.db \
    # Воспроизводимость: не автообновлять CLI-агентов в фоне.
    DISABLE_AUTOUPDATER=1

# ── AI CLI-агенты (BYO-подписка): claude + codex вшиваются в образ ─────────────
# Нужны для scoring_engine=cli. Авторизация — НЕ в образе: через смонтированный
# host-логин (~/.claude, ~/.codex) или токен/ключ в окружении (см. compose.yml и
# страницу web-UI «AI · авторизация»). claude — нативный установщик (без Node),
# codex — релизный musl-бинарь под арх контейнера.
ARG CLAUDE_VERSION=2.1.176
ARG CODEX_VERSION=0.142.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL https://claude.ai/install.sh | bash -s "$CLAUDE_VERSION" \
 && arch="$(uname -m)" \
 && case "$arch" in \
        aarch64|arm64) codex_arch=aarch64 ;; \
        x86_64|amd64) codex_arch=x86_64 ;; \
        *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac \
 && curl -fsSL "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${codex_arch}-unknown-linux-musl.tar.gz" -o /tmp/codex.tgz \
 && tar -xzf /tmp/codex.tgz -C /tmp \
 && mv "/tmp/codex-${codex_arch}-unknown-linux-musl" /usr/local/bin/codex \
 && chmod +x /usr/local/bin/codex \
 && rm -f /tmp/codex.tgz \
 && claude --version && codex --version

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
