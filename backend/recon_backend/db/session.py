"""SQLAlchemy async engine, sessionmaker, init."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

# БД-файл поряд з бекендом, не в /tmp — так його легше бекапити.
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "recon.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Створити всі таблиці. Викликається при старті FastAPI lifespan.

    Для майбутніх схема-змін використовуватимемо Alembic міграції.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency для FastAPI ендпоінтів."""
    async with async_session() as session:
        yield session
