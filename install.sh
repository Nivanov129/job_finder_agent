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

# retry <попыток> <пауза_сек> <команда…> — для шагов, где бывает временный сбой
# сети/реестра Docker (например, pull образа отвалился с EOF).
retry() {
  tries="$1"; pause="$2"; shift 2
  i=1
  while :; do
    if "$@"; then return 0; fi
    if [ "$i" -ge "$tries" ]; then return 1; fi
    warn "Не вышло с попытки $i/$tries (часто временный сбой сети/реестра Docker) — повтор через ${pause}с…"
    i=$((i + 1)); sleep "$pause"
  done
}

# --- 1. Docker (ставим сами, если нет) -------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"

# Дождаться, пока демон Docker ответит (после запуска приложения это не мгновенно).
start_docker_and_wait() {
  if ! docker info >/dev/null 2>&1; then
    info "Запускаю Docker…"
    case "$OS" in
      Darwin) open -a Docker >/dev/null 2>&1 || true ;;
      Linux)  sudo systemctl enable --now docker >/dev/null 2>&1 \
                || sudo service docker start >/dev/null 2>&1 || true ;;
    esac
    info "Жду готовности Docker (до ~3 минут; может попросить пароль или принять условия)…"
    for _ in $(seq 1 90); do
      docker info >/dev/null 2>&1 && break
      sleep 2
    done
  fi
  if ! docker info >/dev/null 2>&1; then
    error "Docker не поднялся. Открой Docker Desktop вручную, дождись готовности и запусти снова:"
    error "  $DOCKER_DESKTOP_URL"
    exit 1
  fi
}

install_docker_macos() {
  if command -v brew >/dev/null 2>&1; then
    info "Ставлю Docker Desktop через Homebrew…"
    brew install --cask docker
  else
    case "$ARCH" in
      arm64) url="https://desktop.docker.com/mac/main/arm64/Docker.dmg" ;;
      *)     url="https://desktop.docker.com/mac/main/amd64/Docker.dmg" ;;
    esac
    local tmp dmg
    tmp="$(mktemp -d)"; dmg="$tmp/Docker.dmg"
    info "Скачиваю Docker Desktop (~600 МБ — это займёт время)…"
    curl -fSL --progress-bar "$url" -o "$dmg" || return 1
    info "Устанавливаю Docker (потребуется пароль администратора)…"
    sudo hdiutil attach "$dmg" -nobrowse -quiet || return 1
    local rc=0
    sudo /Volumes/Docker/Docker.app/Contents/MacOS/install --accept-license || rc=$?
    hdiutil detach /Volumes/Docker -quiet >/dev/null 2>&1 || true
    rm -rf "$tmp"
    return "$rc"
  fi
}

install_docker_linux() {
  info "Ставлю Docker Engine (официальный скрипт get.docker.com, нужен sudo)…"
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh || return 1
  sudo sh /tmp/get-docker.sh || return 1
  sudo usermod -aG docker "$USER" 2>/dev/null || true
}

if ! command -v docker >/dev/null 2>&1; then
  warn "Docker не найден — поставлю автоматически (это нормально для первого запуска)."
  case "$OS" in
    Darwin)
      install_docker_macos || {
        error "Не смог поставить Docker сам. Поставь вручную и запусти снова: $DOCKER_DESKTOP_URL"
        exit 1
      } ;;
    Linux)
      install_docker_linux || {
        error "Не смог поставить Docker сам. Поставь вручную: https://docs.docker.com/engine/install/"
        exit 1
      } ;;
    *)
      error "Не знаю, как поставить Docker на эту систему. Поставь вручную: $DOCKER_DESKTOP_URL"
      exit 1 ;;
  esac
fi

start_docker_and_wait

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
retry 3 8 "${COMPOSE[@]}" build \
  || { error "Сборка не удалась. Проверь интернет и запусти снова."; exit 1; }

info "Поднимаю стек (пайплайн + SearXNG + прогрев модели эмбеддингов)…"
# pull образов из Docker Hub иногда отваливается с EOF — повторяем.
retry 5 6 "${COMPOSE[@]}" up -d || {
  error "Стек не поднялся (похоже, временный сбой загрузки образов из Docker Hub)."
  error "Проверь интернет и запусти снова — собранное закэшировано, будет быстро:"
  error "  cd \"$REPO_DIR\" && ${COMPOSE[*]} up -d"
  exit 1
}

# --- 4. Открыть веб-интерфейс ----------------------------------------------
# Настройка, подбор и подборка — в web-UI (config.json можно править и руками).
WEBUI_URL="http://localhost:8766"
open_ui() {
  if command -v open >/dev/null 2>&1; then           # macOS
    open "$WEBUI_URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then      # Linux desktop
    xdg-open "$WEBUI_URL" >/dev/null 2>&1 || true
  fi
}
open_ui

cat <<EOF

Готово. Стек запущен в фоне.
  Веб-интерфейс:  $WEBUI_URL   ← настройка, подбор и подборка здесь
  (UI доступен сразу; лёгкая модель пред-фильтра ~0.22 ГБ догружается в фоне —
   её можно вообще выключить в «Настройка → Выхлоп»)
  Папка программы: $REPO_DIR
  (вся программа и данные — внутри этой одной папки, нигде больше)
  Конфиг (опц.):  $CONFIG_PATH
  Логи:           ${COMPOSE[*]} logs -f
  Остановить:     ${COMPOSE[*]} down
  Удалить целиком: ${COMPOSE[*]} down -v && rm -rf "$REPO_DIR"

Дальше: открой $WEBUI_URL → «Настройка» (резюме, направления, источники),
затем «AI · авторизация» и «Telegram». Always-on работает, пока хост включён.
EOF
