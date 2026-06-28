#!/usr/bin/env bash
# Job Agent — тонкий установщик (macOS/Linux).
#
# Что делает:
#   1. проверяет, что Docker установлен и демон запущен (нет → ссылка на Docker
#      Desktop, установка самого Docker — на пользователе);
#   2. готовит каталог данных и кладёт туда config.json из примера при первом
#      запуске (резюме/шаблоны/карту поиска участник дополняет сам);
#   3. собирает/тянет образы и поднимает стек через compose.yml;
#   4. открывает config.json в редакторе для заполнения.
#
# Идемпотентность: повторный запуск не перетирает существующий config.json и
# просто пересобирает/поднимает стек.

set -euo pipefail

# Корень репозитория = каталог скрипта, чтобы запуск работал из любого места.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# Каталог данных участника (config.json, резюме, шаблоны, карта, выходной xlsx).
DATA_DIR="${JOB_AGENT_DATA:-./data}"
DOCKER_DESKTOP_URL="https://www.docker.com/products/docker-desktop/"

info()  { printf '\033[0;36m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[0;33m!!\033[0m %s\n' "$*" >&2; }
error() { printf '\033[0;31mxx\033[0m %s\n' "$*" >&2; }

# --- 1. Docker -------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  error "Docker не найден. Установите Docker Desktop и запустите снова:"
  error "  $DOCKER_DESKTOP_URL"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  error "Docker установлен, но демон не отвечает. Запустите Docker Desktop и повторите."
  error "  $DOCKER_DESKTOP_URL"
  exit 1
fi

# Compose v2 (плагин `docker compose`) или legacy `docker-compose`.
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  error "Docker Compose не найден. Обновите Docker Desktop (включает Compose v2):"
  error "  $DOCKER_DESKTOP_URL"
  exit 1
fi
info "Docker и Compose на месте."

# --- 2. Каталог данных и конфиг -------------------------------------------
mkdir -p "$DATA_DIR"
CONFIG_PATH="$DATA_DIR/config.json"
if [ -f "$CONFIG_PATH" ]; then
  info "Конфиг уже есть: $CONFIG_PATH (не трогаю)."
else
  cp config.example.json "$CONFIG_PATH"
  info "Создал $CONFIG_PATH из config.example.json — заполните треки, резюме, каналы, выхлоп."
fi

# --- 3. Сборка и запуск стека ---------------------------------------------
info "Собираю образы (первый раз тянет базовые слои — это нормально долго)…"
"${COMPOSE[@]}" build

info "Поднимаю стек (пайплайн + SearXNG + прогрев модели эмбеддингов)…"
"${COMPOSE[@]}" up -d

# --- 4. Открыть конфиг для заполнения --------------------------------------
open_config() {
  if [ -n "${EDITOR:-}" ]; then
    "$EDITOR" "$CONFIG_PATH" || true
  elif command -v open >/dev/null 2>&1; then        # macOS
    open "$CONFIG_PATH" || true
  elif command -v xdg-open >/dev/null 2>&1; then     # Linux desktop
    xdg-open "$CONFIG_PATH" >/dev/null 2>&1 || true
  else
    warn "Не нашёл, чем открыть конфиг — отредактируйте вручную: $CONFIG_PATH"
  fi
}
open_config

cat <<EOF

Готово. Стек запущен в фоне.
  Конфиг:       $CONFIG_PATH
  Логи:         ${COMPOSE[*]} logs -f pipeline
  Backfill:     ${COMPOSE[*]} run --rm pipeline backfill --days 14 --config /data/config.json --out /data/job-agent-result.xlsx
  Остановить:   ${COMPOSE[*]} down

Always-on: ночной мониторинг работает, только пока хост включён (см. README).
EOF
