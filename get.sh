#!/bin/sh
# Job Agent — установка одной командой (macOS/Linux):
#
#   curl -fsSL https://raw.githubusercontent.com/Nivanov129/job_finder_agent/main/get.sh | sh
#
# Что делает: скачивает проект в ~/job-agent (git или tar.gz — без git тоже
# работает), затем запускает ./install.sh, который сам ставит Docker (если нет),
# собирает образы, поднимает стек и открывает веб-интерфейс.
#
# Идемпотентно: если папка уже есть — код обновляется, данные (резюме, конфиг,
# .env, авторизация) НЕ трогаются.

set -eu

REPO_URL="https://github.com/Nivanov129/job_finder_agent"
BRANCH="main"
TARBALL="$REPO_URL/archive/refs/heads/$BRANCH.tar.gz"
DIR="${JOB_AGENT_HOME:-$HOME/job-agent}"

info() { printf '\033[0;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m!!\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31mxx\033[0m %s\n' "$*" >&2; }

command -v curl >/dev/null 2>&1 || { err "Нужен curl (обычно уже есть)."; exit 1; }

info "Всё ставится в ОДНУ папку: $DIR (программа и данные — только там, ничего не разбрасываю по системе)."

if [ -d "$DIR" ]; then
  info "Папка уже есть — обновляю до последней версии, данные (резюме/конфиг/.env) не трогаю."
  if [ -d "$DIR/.git" ] && command -v git >/dev/null 2>&1; then
    # Жёсткая синхронизация с remote — надёжно даже если историю переписывали
    # (обычный pull тогда падает). Данные (data/) gitignored — не трогаются.
    if git -C "$DIR" fetch --quiet origin 2>/dev/null \
       && git -C "$DIR" reset --hard "origin/$BRANCH" --quiet 2>/dev/null; then
      info "код обновлён до последней версии."
    else
      warn "не смог обновить код — продолжаю с текущим."
    fi
  else
    # Не git-папка (скачано tar.gz) — стягиваем свежий код поверх (data/ в архиве
    # нет, поэтому резюме/конфиг/.env не затрагиваются).
    tmp="$(mktemp -d)"
    if curl -fsSL "$TARBALL" | tar xz -C "$tmp" 2>/dev/null; then
      for src in "$tmp"/job_finder_agent-*; do
        [ -d "$src" ] && cp -R "$src/." "$DIR/" && info "код обновлён до последней версии."
      done
    else
      warn "не смог скачать обновление — продолжаю с текущим."
    fi
    rm -rf "$tmp"
  fi
else
  info "Скачиваю Job Agent в каталог: ${DIR}"
  if command -v git >/dev/null 2>&1; then
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL.git" "$DIR"
  else
    tmp="$(mktemp -d)"
    curl -fsSL "$TARBALL" | tar xz -C "$tmp"
    mv "$tmp"/job_finder_agent-* "$DIR"
    rm -rf "$tmp"
  fi
fi

cd "$DIR"
chmod +x install.sh 2>/dev/null || true
info "Запускаю установщик (он сам поставит Docker, если нужно)…"

# install.sh использует bash (массивы) — запускаем им, если есть; иначе шебангом.
if command -v bash >/dev/null 2>&1; then
  exec bash install.sh
else
  exec ./install.sh
fi
