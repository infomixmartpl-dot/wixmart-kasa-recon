@echo off
REM start-backend.bat - run backend in dev mode.
REM Plain ASCII to avoid Windows CP866/CP1251 encoding issues on .bat files.

setlocal
cd /d "%~dp0\..\backend"

if not exist .venv\Scripts\python.exe (
    echo [FAIL] Venv not found. Run scripts\setup-windows.ps1 first.
    pause
    exit /b 1
)

echo === Kasa Recon backend ===
echo Listens on http://127.0.0.1:8765
echo Logs: %%LOCALAPPDATA%%\KasaRecon\backend.log
echo DB:   %%LOCALAPPDATA%%\KasaRecon\recon.db
echo.
echo Press Ctrl+C to stop.
echo.

.venv\Scripts\python.exe -m recon_backend.launcher

pause
