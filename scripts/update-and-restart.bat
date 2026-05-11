@echo off
REM update-and-restart.bat - quick git pull + backend restart.
REM Plain ASCII to avoid encoding issues.

setlocal
cd /d "%~dp0\.."

echo === Pulling commits from GitHub ===
git pull --ff-only
if errorlevel 1 (
    echo.
    echo [FAIL] Pull failed. Likely local changes or merge conflict.
    echo Resolve manually via Git or GitHub Desktop.
    pause
    exit /b 1
)

echo.
echo === Updating dependencies (if changed) ===
cd backend
.venv\Scripts\pip install -e . --quiet
cd ..

echo.
echo === Killing old backend (if still running on 8765) ===
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8765 ^| findstr LISTENING') do (
    echo Killing PID %%a
    taskkill /F /PID %%a 2>nul
)

echo.
echo === Starting fresh backend in new window ===
start "Kasa Recon Backend" /D "%~dp0..\backend" "%~dp0..\backend\.venv\Scripts\python.exe" -m recon_backend.launcher

echo.
echo [OK] Done. Backend running in background. UI (kasa_recon.exe) will pick up new data.
timeout /t 3 >nul
