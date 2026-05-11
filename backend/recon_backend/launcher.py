"""Entry point для PyInstaller — запуск FastAPI як standalone exe.

Викликається в одному з двох сценаріїв:
1. У звичайному dev-режимі (`python -m recon_backend.launcher`).
2. Як `recon_backend.exe` запакований PyInstaller-ом — Flutter стартує його
   як subprocess.

Поведінка:
- Слухає на 127.0.0.1:8765 (фіксований порт, тільки локально — не з мережі).
- Логи у %LOCALAPPDATA%\\KasaRecon\\backend.log (Windows) або ~/.kasa_recon/backend.log.
- Обробляє SIGINT/SIGTERM → м'який shutdown.

Порт 8765 спеціально не 8000, щоб не конфліктував з користувацькими сервісами.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import signal
import sys
from pathlib import Path

import uvicorn

# Фіксований порт для embedded режиму — UI знає його точно.
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8765


def app_data_dir() -> Path:
    """Повертає папку для БД/логів — `%LOCALAPPDATA%\\KasaRecon` (Win) або `~/.kasa_recon`."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "KasaRecon"
    return Path.home() / ".kasa_recon"


def setup_logging() -> None:
    """Файлове логування з ротацією 5 файлів по 2 МБ."""
    data_dir = app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    log_file = data_dir / "backend.log"

    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # У режимі PyInstaller stdout/stderr перенаправлений у nul,
    # тому ще додаємо stream-handler коли є tty (dev режим).
    if sys.stdout and sys.stdout.isatty():
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    logging.info("=== Старт бекенду; logs у %s ===", log_file)


def install_signal_handlers(server: uvicorn.Server) -> None:
    """SIGINT/SIGTERM → попросити server виключитись gracefully."""

    def _shutdown(signum: int, frame) -> None:  # noqa: ARG001
        logging.info("Отримано сигнал %s, завершуюсь...", signum)
        server.should_exit = True

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)


def run() -> None:
    """Точка запуску для PyInstaller (`recon_backend.exe`) і CLI."""
    setup_logging()

    # Налаштовуємо БД _до_ імпорту FastAPI app, щоб моделі побачили правильний шлях.
    os.environ.setdefault("KASA_RECON_DATA_DIR", str(app_data_dir()))

    from .main import app  # noqa: PLC0415 — пізній імпорт навмисно

    config = uvicorn.Config(
        app,
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        log_level="info",
        access_log=False,
        # uvicorn вже піднявся з нашими логерами — не перевизначаємо.
        log_config=None,
    )
    server = uvicorn.Server(config)
    install_signal_handlers(server)
    server.run()


if __name__ == "__main__":
    run()
