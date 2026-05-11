"""SQLAlchemy async engine, sessionmaker, init.

БД-файл лежить:
- Якщо встановлено `KASA_RECON_DATA_DIR` (через launcher.py для embedded режиму) —
  у тій папці (зазвичай `%LOCALAPPDATA%\\KasaRecon`). Зберігається між апдейтами .exe.
- Інакше — поряд з backend/ (зручно для розробки).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


def _resolve_db_path() -> Path:
    """Шлях до файлу SQLite — embedded або dev."""
    env_dir = os.environ.get("KASA_RECON_DATA_DIR")
    if env_dir:
        data_dir = Path(env_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "recon.db"
    # Dev — поряд з backend/.
    return Path(__file__).resolve().parent.parent.parent / "recon.db"


DB_PATH = _resolve_db_path()
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Створити всі таблиці. Викликається при старті FastAPI lifespan."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
