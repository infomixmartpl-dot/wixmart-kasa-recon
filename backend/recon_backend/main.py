"""FastAPI додаток.

Запуск локально для розробки:
    uv run uvicorn recon_backend.main:app --reload --port 8000

Або з backend/ кореня:
    cd backend && .venv/bin/uvicorn recon_backend.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import bank_accounts, cash_accounts, fops, odata, pidrozdily, recon, statti, sync
from .api.schemas import HealthOut
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Створити схему БД на старті."""
    await init_db()
    yield


app = FastAPI(
    title="WixMart Kasa Recon",
    description="Бекенд звірки ПриватБанк ↔ Каса 1С УНФ 1.6",
    version=__version__,
    lifespan=lifespan,
)

# CORS — Flutter Desktop може ходити з будь-якого порту в dev-режимі.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: обмежити в production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthOut)
async def health():
    """Простий health-чек для UI і моніторингу."""
    from sqlalchemy import text
    from .db.session import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:  # noqa: BLE001
        db_status = f"error: {e}"

    return HealthOut(status="ok", version=__version__, db=db_status)


# Реєструємо роутери з кожного модуля.
app.include_router(fops.router, prefix="/api/fops", tags=["ФОПи"])
app.include_router(bank_accounts.router, prefix="/api/bank-accounts", tags=["Банк-рахунки"])
app.include_router(cash_accounts.router, prefix="/api/cash-accounts", tags=["Каси 1С"])
app.include_router(pidrozdily.router, prefix="/api/pidrozdily", tags=["Підрозділи"])
app.include_router(statti.router, prefix="/api/statti", tags=["Статті руху коштів"])
app.include_router(sync.router, prefix="/api/sync", tags=["Синк даних"])
app.include_router(odata.router, prefix="/api/odata", tags=["1С OData"])
app.include_router(recon.router, prefix="/api/recon", tags=["Звірка"])
