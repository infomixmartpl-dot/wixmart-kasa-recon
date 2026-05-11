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

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


# SQLite за замовч. ігнорує FOREIGN KEY — каскадні DELETE не спрацьовують,
# і ORM cascade у async-режимі зависає на lazy-load. Вмикаємо FK глобально.
@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_conn, _connection_record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


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
    """Створити всі таблиці + легкі міграції для існуючих БД."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Міграція v2: додати match_row.user_status і .manual якщо ще нема.
        r = await conn.execute(text("PRAGMA table_info(match_row)"))
        cols = {row[1] for row in r.fetchall()}
        if "user_status" not in cols:
            await conn.execute(text("ALTER TABLE match_row ADD COLUMN user_status VARCHAR(20)"))
        if "manual" not in cols:
            await conn.execute(text("ALTER TABLE match_row ADD COLUMN manual BOOLEAN DEFAULT 0 NOT NULL"))


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
