@echo off
REM start-backend.bat — запустити бекенд у dev-режимі.
REM Юзер просто двічі клацає на цей файл — відкривається консоль з логами бекенду.

setlocal
cd /d "%~dp0\..\backend"

if not exist .venv\Scripts\python.exe (
    echo Venv не знайдено! Запусти спочатку scripts\setup-windows.ps1
    pause
    exit /b 1
)

echo === Kasa Recon backend ===
echo Слухає на http://127.0.0.1:8765
echo Логи: %%LOCALAPPDATA%%\KasaRecon\backend.log
echo База: %%LOCALAPPDATA%%\KasaRecon\recon.db
echo.
echo Натисни Ctrl+C щоб зупинити.
echo.

.venv\Scripts\python.exe -m recon_backend.launcher

REM Якщо процес закрився сам — нехай вікно залишиться щоб юзер прочитав помилку.
pause
