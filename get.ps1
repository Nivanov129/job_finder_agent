# Job Agent — установка одной командой (Windows, PowerShell):
#
#   irm https://raw.githubusercontent.com/Nivanov129/job_finder_agent/main/get.ps1 | iex
#
# Скачивает проект в %USERPROFILE%\job-agent (git или zip), затем запускает
# install.ps1, который сам ставит Docker (через winget), собирает образы,
# поднимает стек и открывает веб-интерфейс. Идемпотентно: данные не трогает.

$ErrorActionPreference = 'Stop'

$RepoUrl = 'https://github.com/Nivanov129/job_finder_agent'
$Branch  = 'main'
$ZipUrl  = "$RepoUrl/archive/refs/heads/$Branch.zip"
$Dir     = if ($env:JOB_AGENT_HOME) { $env:JOB_AGENT_HOME } else { Join-Path $env:USERPROFILE 'job-agent' }

function Write-Info { param($m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Warn { param($m) Write-Host "!! $m"  -ForegroundColor Yellow }

Write-Info "Всё ставится в ОДНУ папку: $Dir (программа и данные — только там)."

if (Test-Path $Dir) {
  Write-Info "Папка уже есть — обновляю до последней версии, данные (резюме/конфиг/.env) не трогаю."
  if ((Test-Path (Join-Path $Dir '.git')) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    # Жёсткая синхронизация — надёжно даже если историю переписывали (data/ gitignored).
    try {
      git -C $Dir fetch --quiet origin | Out-Null
      git -C $Dir reset --hard "origin/$Branch" --quiet | Out-Null
      Write-Info "код обновлён до последней версии."
    } catch { Write-Warn "не смог обновить код — продолжаю с текущим." }
  } else {
    # Не git-папка (zip) — стягиваем свежий код поверх (data/ в архиве нет).
    try {
      $tmp = Join-Path $env:TEMP ("ja_" + [guid]::NewGuid().ToString('N'))
      New-Item -ItemType Directory -Force -Path $tmp | Out-Null
      $zip = Join-Path $tmp 'src.zip'
      Invoke-WebRequest -Uri $ZipUrl -OutFile $zip
      Expand-Archive -Path $zip -DestinationPath $tmp -Force
      $src = Get-ChildItem -Path $tmp -Directory | Where-Object { $_.Name -like 'job_finder_agent-*' } | Select-Object -First 1
      Copy-Item -Path (Join-Path $src.FullName '*') -Destination $Dir -Recurse -Force
      Remove-Item -Recurse -Force $tmp
      Write-Info "код обновлён до последней версии."
    } catch { Write-Warn "не смог обновить код — продолжаю с текущим." }
  }
} else {
  Write-Info "Скачиваю Job Agent в $Dir…"
  if (Get-Command git -ErrorAction SilentlyContinue) {
    git clone --depth 1 --branch $Branch "$RepoUrl.git" $Dir
  } else {
    $tmp = Join-Path $env:TEMP ("ja_" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $zip = Join-Path $tmp 'main.zip'
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $extracted = Get-ChildItem -Path $tmp -Directory | Where-Object { $_.Name -like 'job_finder_agent-*' } | Select-Object -First 1
    Move-Item $extracted.FullName $Dir
    Remove-Item -Recurse -Force $tmp
  }
}

Set-Location $Dir
Write-Info "Запускаю установщик (он сам поставит Docker, если нужно)…"
& powershell -ExecutionPolicy Bypass -File (Join-Path $Dir 'install.ps1')
