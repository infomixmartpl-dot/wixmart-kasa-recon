# setup-windows.ps1 — одноразова установка бекенду на Windows.
#
# Запуск (з кореня репо):
#   .\scripts\setup-windows.ps1
#
# Що робить:
#   1. Перевіряє що Python 3.11+ доступний.
#   2. Створює virtualenv у backend\.venv\
#   3. Встановлює всі залежності бекенду.
#   4. Робить швидкий smoke-тест (імпорт FastAPI app).
#
# Після цього: запускай `scripts\start-backend.bat` щоб підняти бекенд.

$ErrorActionPreference = "Stop"

Write-Host "=== Kasa Recon backend setup ===" -ForegroundColor Cyan
Write-Host ""

# 1. Python check
try {
    $pyVersion = python --version 2>&1
    Write-Host "✓ Знайдено $pyVersion" -ForegroundColor Green
}
catch {
    Write-Host "✗ Python не знайдено в PATH." -ForegroundColor Red
    Write-Host "  Скачай з https://python.org/downloads/ (3.11.x), при встановленні постав галочку 'Add to PATH'." -ForegroundColor Yellow
    exit 1
}

# Перевірка версії (мінімум 3.11)
$verNum = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([Version]$verNum -lt [Version]"3.11") {
    Write-Host "✗ Потрібен Python 3.11+, знайдено $verNum" -ForegroundColor Red
    exit 1
}

# 2. Venv
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$venvDir = Join-Path $backendDir ".venv"

if (Test-Path $venvDir) {
    Write-Host "⏭  Venv вже існує у $venvDir" -ForegroundColor Yellow
}
else {
    Write-Host "📦 Створюю venv у $venvDir..." -ForegroundColor Cyan
    Push-Location $backendDir
    python -m venv .venv
    Pop-Location
    Write-Host "✓ Venv створено" -ForegroundColor Green
}

# 3. Install deps
Write-Host ""
Write-Host "📦 Встановлюю залежності бекенду (це може зайняти 1-2 хв)..." -ForegroundColor Cyan
$pip = Join-Path $venvDir "Scripts\pip.exe"
Push-Location $backendDir
& $pip install --upgrade pip --quiet
& $pip install -e . --quiet
Pop-Location
Write-Host "✓ Залежності встановлено" -ForegroundColor Green

# 4. Smoke test
Write-Host ""
Write-Host "🔬 Smoke test (імпорт FastAPI app)..." -ForegroundColor Cyan
$py = Join-Path $venvDir "Scripts\python.exe"
Push-Location $backendDir
& $py -c "from recon_backend.main import app; print('Routes:', len([r for r in app.routes if hasattr(r, 'methods')]))"
Pop-Location

Write-Host ""
Write-Host "=== Готово ===" -ForegroundColor Green
Write-Host ""
Write-Host "Наступний крок: подвійний клік на scripts\start-backend.bat" -ForegroundColor Cyan
Write-Host "(або з PowerShell: .\scripts\start-backend.bat)" -ForegroundColor Gray
