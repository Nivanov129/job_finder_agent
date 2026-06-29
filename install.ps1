# Job Agent — тонкий установщик (Windows, PowerShell).
#
# Что делает:
#   1. проверяет, что Docker установлен и демон запущен (нет → ссылка на Docker
#      Desktop, установка самого Docker — на пользователе);
#   2. если это git-клон — подтягивает свежий код из git (чтобы повторный запуск
#      ставил последние обновления, а не пересобирал старьё);
#   3. готовит каталог данных и кладёт туда config.json из примера при первом
#      запуске (резюме/шаблоны/карту поиска участник дополняет сам);
#   4. собирает образы заново и поднимает стек через compose.yml;
#   5. открывает веб-интерфейс.
#
# Идемпотентность: повторный запуск не перетирает существующий config.json,
# подтягивает обновления кода и пересобирает/поднимает стек на свежем коде.

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

# --- 1. Docker (ставим сами, если нет) -------------------------------------
function Wait-Docker {
  Write-Info "Жду готовности Docker (до ~3 минут; Docker Desktop может попросить принять условия)…"
  for ($i = 0; $i -lt 90; $i++) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { return $true }
    Start-Sleep -Seconds 2
  }
  return $false
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Warn "Docker не найден — ставлю автоматически (это нормально для первого запуска)."
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Info "Ставлю Docker Desktop через winget…"
    winget install -e --id Docker.DockerDesktop --accept-source-agreements --accept-package-agreements
  } else {
    Write-Err "Не нашёл winget для авто-установки. Поставь Docker Desktop вручную и запусти снова:"
    Write-Err "  $DockerDesktopUrl"
    exit 1
  }
  # обновить PATH в текущей сессии, чтобы увидеть свежий docker
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}

# Запустить Docker Desktop и дождаться демона.
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Info "Запускаю Docker Desktop…"
  $dd = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
  if (Test-Path $dd) { Start-Process $dd } else { Start-Process 'Docker Desktop' -ErrorAction SilentlyContinue }
  if (-not (Wait-Docker)) {
    Write-Err "Docker не поднялся. Открой Docker Desktop вручную, дождись готовности и запусти снова:"
    Write-Err "  $DockerDesktopUrl"
    exit 1
  }
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

# --- 2. Обновление кода из git --------------------------------------------
# Образ собирается ИМЕННО из текущих файлов репозитория. Чтобы повторный запуск
# принёс свежие правки, подтягиваем их из git (если это клон). Локальные
# изменения отслеживаемых файлов и не-git-каталоги не трогаем.
function Update-FromGit {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Info 'git не найден — пропускаю обновление кода (собираю из текущих файлов).'; return
  }
  git -C $RepoDir rev-parse --is-inside-work-tree *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Info 'Не git-репозиторий — пропускаю обновление кода (использую файлы как есть).'; return
  }
  $dirty = git -C $RepoDir status --porcelain --untracked-files=no
  if ($dirty) {
    Write-Warn 'Есть локальные изменения отслеживаемых файлов — пропускаю git pull, чтобы их не потерять.'; return
  }
  $branch = (git -C $RepoDir rev-parse --abbrev-ref HEAD).Trim()
  Write-Info "Тяну последние обновления из git (ветка $branch)…"
  git -C $RepoDir pull --ff-only origin $branch
  if ($LASTEXITCODE -eq 0) { Write-Info 'Код обновлён до последней версии.' }
  else { Write-Warn 'git pull не удался (сеть/конфликт) — продолжаю на текущем коде.' }
}
Update-FromGit

# --- 3. Каталог данных и конфиг -------------------------------------------
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$ConfigPath = Join-Path $DataDir 'config.json'
if (Test-Path $ConfigPath) {
  Write-Info "Конфиг уже есть: $ConfigPath (не трогаю)."
} else {
  Copy-Item 'config.example.json' $ConfigPath
  Write-Info "Создал $ConfigPath из config.example.json — заполните треки, резюме, каналы, выхлоп."
}

# --- 4. Сборка и запуск стека ---------------------------------------------
$ComposeExe = $Compose[0]
$ComposeArgs = @($Compose[1..($Compose.Length - 1)])

# Повтор шага при временном сбое сети/реестра Docker (pull образа с EOF и т.п.).
function Invoke-Retry {
  param([int]$Tries, [int]$Pause, [scriptblock]$Action)
  for ($i = 1; $i -le $Tries; $i++) {
    & $Action
    if ($LASTEXITCODE -eq 0) { return }
    if ($i -lt $Tries) {
      Write-Warn "Не вышло с попытки $i/$Tries (часто временный сбой сети/реестра Docker) — повтор через $Pause с…"
      Start-Sleep -Seconds $Pause
    }
  }
  throw "Шаг не удался после $Tries попыток. Проверь интернет и запусти снова."
}

Write-Info "Собираю образы заново (свежий код + кэш слоёв — обычно быстро)…"
Invoke-Retry -Tries 3 -Pause 8 -Action { & $ComposeExe @ComposeArgs build }

Write-Info "Поднимаю стек (пайплайн + SearXNG + прогрев модели эмбеддингов)…"
Invoke-Retry -Tries 5 -Pause 6 -Action { & $ComposeExe @ComposeArgs up -d }

# --- 5. Открыть веб-интерфейс ----------------------------------------------
# Настройка, подбор и подборка — в web-UI (config.json можно править и руками).
$WebUiUrl = 'http://localhost:8766'
try {
  Start-Process $WebUiUrl
} catch {
  Write-Warn "Открой вручную в браузере: $WebUiUrl"
}

$ComposeShown = $Compose -join ' '
Write-Host ""
Write-Host "Готово. Стек запущен в фоне."
Write-Host "  Веб-интерфейс:   $WebUiUrl   <- настройка, подбор и подборка здесь"
Write-Host "  (UI доступен сразу; лёгкая модель пред-фильтра ~0.22 ГБ грузится в фоне,"
Write-Host "   её можно выключить в «Настройка -> Выхлоп»)"
Write-Host "  Папка программы: $RepoDir"
Write-Host "  (вся программа и данные - внутри этой одной папки, нигде больше)"
Write-Host "  Конфиг (опц.):   $ConfigPath"
Write-Host "  Логи:            $ComposeShown logs -f"
Write-Host "  Остановить:      $ComposeShown down"
Write-Host "  Удалить целиком: $ComposeShown down -v; Remove-Item -Recurse -Force '$RepoDir'"
Write-Host ""
Write-Host "Дальше: открой $WebUiUrl -> «Настройка», затем «AI · авторизация» и «Telegram»."
