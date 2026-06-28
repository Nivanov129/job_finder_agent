# Job Agent — тонкий установщик (Windows, PowerShell).
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

$ErrorActionPreference = 'Stop'

# Корень репозитория = каталог скрипта, чтобы запуск работал из любого места.
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoDir

# Каталог данных участника (config.json, резюме, шаблоны, карта, выходной xlsx).
$DataDir = if ($env:JOB_AGENT_DATA) { $env:JOB_AGENT_DATA } else { './data' }
$DockerDesktopUrl = 'https://www.docker.com/products/docker-desktop/'

function Write-Info  { param($m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Warn  { param($m) Write-Host "!! $m"  -ForegroundColor Yellow }
function Write-Err   { param($m) Write-Host "xx $m"  -ForegroundColor Red }

# --- 1. Docker -------------------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Err "Docker не найден. Установите Docker Desktop и запустите снова:"
  Write-Err "  $DockerDesktopUrl"
  exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Err "Docker установлен, но демон не отвечает. Запустите Docker Desktop и повторите."
  Write-Err "  $DockerDesktopUrl"
  exit 1
}

# Compose v2 (плагин `docker compose`) или legacy `docker-compose`.
docker compose version *> $null
if ($LASTEXITCODE -eq 0) {
  $Compose = @('docker', 'compose')
} elseif (Get-Command docker-compose -ErrorAction SilentlyContinue) {
  $Compose = @('docker-compose')
} else {
  Write-Err "Docker Compose не найден. Обновите Docker Desktop (включает Compose v2):"
  Write-Err "  $DockerDesktopUrl"
  exit 1
}
Write-Info "Docker и Compose на месте."

# --- 2. Каталог данных и конфиг -------------------------------------------
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$ConfigPath = Join-Path $DataDir 'config.json'
if (Test-Path $ConfigPath) {
  Write-Info "Конфиг уже есть: $ConfigPath (не трогаю)."
} else {
  Copy-Item 'config.example.json' $ConfigPath
  Write-Info "Создал $ConfigPath из config.example.json — заполните треки, резюме, каналы, выхлоп."
}

# --- 3. Сборка и запуск стека ---------------------------------------------
$ComposeExe = $Compose[0]
$ComposeArgs = @($Compose[1..($Compose.Length - 1)])

Write-Info "Собираю образы (первый раз тянет базовые слои — это нормально долго)…"
& $ComposeExe @ComposeArgs build
if ($LASTEXITCODE -ne 0) { throw "compose build вернул $LASTEXITCODE" }

Write-Info "Поднимаю стек (пайплайн + SearXNG + прогрев модели эмбеддингов)…"
& $ComposeExe @ComposeArgs up -d
if ($LASTEXITCODE -ne 0) { throw "compose up вернул $LASTEXITCODE" }

# --- 4. Открыть конфиг для заполнения --------------------------------------
try {
  Invoke-Item $ConfigPath
} catch {
  Write-Warn "Не нашёл, чем открыть конфиг — отредактируйте вручную: $ConfigPath"
}

$ComposeShown = $Compose -join ' '
Write-Host ""
Write-Host "Готово. Стек запущен в фоне."
Write-Host "  Конфиг:       $ConfigPath"
Write-Host "  Логи:         $ComposeShown logs -f pipeline"
Write-Host "  Backfill:     $ComposeShown run --rm pipeline backfill --days 14 --config /data/config.json --out /data/job-agent-result.xlsx"
Write-Host "  Остановить:   $ComposeShown down"
Write-Host ""
Write-Host "Always-on: ночной мониторинг работает, только пока хост включён (см. README)."
