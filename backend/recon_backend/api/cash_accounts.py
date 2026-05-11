"""CRUD кас 1С (об'єктів довідника «Банковский счет, касса»)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import CashAccount, Fop
from ..db.session import get_session
from .schemas import CashAccountCreate, CashAccountOut

router = APIRouter()


@router.get("/", response_model=list[CashAccountOut])
async def list_cash_accounts(
    fop_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(CashAccount).where(CashAccount.fop_id == fop_id).order_by(CashAccount.name_1c))
    return result.scalars().all()


@router.post("/", response_model=CashAccountOut, status_code=status.HTTP_201_CREATED)
async def create_cash_account(
    fop_id: str = Query(...),
    payload: CashAccountCreate = ...,
    session: AsyncSession = Depends(get_session),
):
    fop = await session.get(Fop, fop_id)
    if not fop:
        raise HTTPException(status_code=404, detail="ФОП не знайдено")
    acc = CashAccount(fop_id=fop_id, **payload.model_dump())
    session.add(acc)
    await session.commit()
    await session.refresh(acc)
    return acc


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cash_account(account_id: str, session: AsyncSession = Depends(get_session)):
    acc = await session.get(CashAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Не знайдено")
    await session.delete(acc)
    await session.commit()
    return None
