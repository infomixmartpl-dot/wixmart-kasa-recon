# setup-windows.ps1 — одноразова установка бекенду на Windows.
#
# Запуск (з кореня репо):
#   .\scripts\setup-windows.ps1
#
# Що робить:
#   1. Перевіряє Python 3.11+
#   2. Створює virtualenv у backend\.venv\
#   3. Ставить залежності бекенду
#   4. Робить швидкий smoke-тест (імпорт FastAPI app)

$ErrorActionPreference = "Stop"

Write-Host "=== Kasa Recon backend setup ===" -ForegroundColor Cyan
Write-Host ""

# 1. Python check
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    Write-Host "[FAIL] Python не знайдено в PATH." -ForegroundColor Red
    Write-Host "       Постав Python 3.11.9 з python.org з галочкою 'Add to PATH'." -ForegroundColor Yellow
    exit 1
}
$pyVersion = python --version 2>&1
Write-Host "[OK] $pyVersion" -ForegroundColor Green

# Перевірка версії (мінімум 3.11)
$verNum = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([Version]$verNum -lt [Version]"3.11") {
    Write-Host "[FAIL] Потрібен Python 3.11+, знайдено $verNum" -ForegroundColor Red
    exit 1
}

# 2. Venv
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$venvDir = Join-Path $backendDir ".venv"

if (Test-Path $venvDir) {
    Write-Host "[SKIP] Venv вже існує у $venvDir" -ForegroundColor Yellow
}
else {
    Write-Host "[..] Створюю venv у $venvDir..." -ForegroundColor Cyan
    Push-Location $backendDir
    python -m venv .venv
    Pop-Location
    Write-Host "[OK] Venv створено" -ForegroundColor Green
}

# 3. Install deps
Write-Host ""
Write-Host "[..] Ставлю залежності бекенду (1-2 хв)..." -ForegroundColor Cyan
$pip = Join-Path $venvDir "Scripts\pip.exe"
Push-Location $backendDir
& $pip install --upgrade pip --quiet
& $pip install -e . --quiet
Pop-Location
Write-Host "[OK] Залежності встановлено" -ForegroundColor Green

# 4. Smoke test
Write-Host ""
Write-Host "[..] Smoke test (імпорт FastAPI app)..." -ForegroundColor Cyan
$py = Join-Path $venvDir "Scripts\python.exe"
Push-Location $backendDir
& $py -c "from recon_backend.main import app; print('Routes:', len([r for r in app.routes if hasattr(r, 'methods')]))"
Pop-Location

Write-Host ""
Write-Host "=== Готово ===" -ForegroundColor Green
Write-Host ""
Write-Host "Наступний крок: подвійний клік на scripts\start-backend.bat" -ForegroundColor Cyan
