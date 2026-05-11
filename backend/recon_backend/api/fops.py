"""CRUD ФОПів."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import BankOp, CashOp, Fop
from ..db.session import get_session
from .schemas import FopCreate, FopOut, FopUpdate

router = APIRouter()


@router.get("/", response_model=list[FopOut])
async def list_fops(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Fop).order_by(Fop.name))
    return result.scalars().all()


@router.post("/", response_model=FopOut, status_code=status.HTTP_201_CREATED)
async def create_fop(payload: FopCreate, session: AsyncSession = Depends(get_session)):
    fop = Fop(**payload.model_dump())
    session.add(fop)
    await session.commit()
    await session.refresh(fop)
    return fop


@router.get("/{fop_id}", response_model=FopOut)
async def get_fop(fop_id: str, session: AsyncSession = Depends(get_session)):
    fop = await session.get(Fop, fop_id)
    if not fop:
        raise HTTPException(status_code=404, detail="ФОП не знайдено")
    return fop


@router.patch("/{fop_id}", response_model=FopOut)
async def update_fop(fop_id: str, payload: FopUpdate, session: AsyncSession = Depends(get_session)):
    fop = await session.get(Fop, fop_id)
    if not fop:
        raise HTTPException(status_code=404, detail="ФОП не знайдено")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(fop, k, v)
    await session.commit()
    await session.refresh(fop)
    return fop


@router.delete("/{fop_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fop(fop_id: str, session: AsyncSession = Depends(get_session)):
    fop = await session.get(Fop, fop_id)
    if not fop:
        raise HTTPException(status_code=404, detail="ФОП не знайдено")
    await session.delete(fop)
    await session.commit()
    return None


@router.get("/{fop_id}/stats")
async def fop_stats(fop_id: str, session: AsyncSession = Depends(get_session)):
    """Скільки операцій у БД для ФОПа і за який діапазон дат — для діагностики."""
    fop = await session.get(Fop, fop_id)
    if not fop:
        raise HTTPException(status_code=404, detail="ФОП не знайдено")

    bank_total = (await session.execute(
        select(func.count(BankOp.id)).where(BankOp.fop_id == fop_id)
    )).scalar() or 0
    bank_min = (await session.execute(
        select(func.min(BankOp.op_date)).where(BankOp.fop_id == fop_id)
    )).scalar()
    bank_max = (await session.execute(
        select(func.max(BankOp.op_date)).where(BankOp.fop_id == fop_id)
    )).scalar()

    cash_total = (await session.execute(
        select(func.count(CashOp.id)).where(CashOp.fop_id == fop_id)
    )).scalar() or 0
    cash_min = (await session.execute(
        select(func.min(CashOp.op_date)).where(CashOp.fop_id == fop_id)
    )).scalar()
    cash_max = (await session.execute(
        select(func.max(CashOp.op_date)).where(CashOp.fop_id == fop_id)
    )).scalar()

    return {
        "fop_id": fop_id,
        "fop_name": fop.name,
        "bank_ops": {
            "total": bank_total,
            "date_min": bank_min.isoformat() if bank_min else None,
            "date_max": bank_max.isoformat() if bank_max else None,
        },
        "cash_ops": {
            "total": cash_total,
            "date_min": cash_min.isoformat() if cash_min else None,
            "date_max": cash_max.isoformat() if cash_max else None,
        },
    }
