@echo off
REM update-and-restart.bat — швидкий цикл «git pull + перезапуск бекенду».
REM Натискаєш коли хочеш підтягнути свіжі зміни з GitHub.

setlocal
cd /d "%~dp0\.."

echo === Pull новi коміти з GitHub ===
git pull --ff-only
if errorlevel 1 (
    echo.
    echo ✗ Не вдалось зробити pull. Можливо є локальні зміни або конфлікт.
    echo Відкрий GitHub Desktop і резолв вручну.
    pause
    exit /b 1
)

echo.
echo === Оновити залежності (якщо змінились) ===
cd backend
.venv\Scripts\pip install -e . --quiet
cd ..

echo.
echo === Зупинити старий бекенд (якщо ще працює) ===
REM Шукаємо процес що слухає 8765 і вбиваємо.
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8765 ^| findstr LISTENING') do (
    echo Killing PID %%a
    taskkill /F /PID %%a 2>nul
)

echo.
echo === Запуск свіжого бекенду в новому вікні ===
start "Kasa Recon Backend" /D "%~dp0..\backend" .venv\Scripts\python.exe -m recon_backend.launcher

echo.
echo ✓ Готово. Бекенд стартує у фоні. Перевір що kasa_recon.exe вже відкрив новi дані.
timeout /t 3 >nul
