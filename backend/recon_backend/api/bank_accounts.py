"""CRUD банк-рахунків ФОПа."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import BankAccount, Fop
from ..db.session import get_session
from .schemas import BankAccountCreate, BankAccountOut

router = APIRouter()


@router.get("/", response_model=list[BankAccountOut])
async def list_bank_accounts(
    fop_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(BankAccount).where(BankAccount.fop_id == fop_id).order_by(BankAccount.label))
    return result.scalars().all()


@router.post("/", response_model=BankAccountOut, status_code=status.HTTP_201_CREATED)
async def create_bank_account(
    fop_id: str = Query(...),
    payload: BankAccountCreate = ...,
    session: AsyncSession = Depends(get_session),
):
    fop = await session.get(Fop, fop_id)
    if not fop:
        raise HTTPException(status_code=404, detail="ФОП не знайдено")
    acc = BankAccount(fop_id=fop_id, **payload.model_dump())
    session.add(acc)
    await session.commit()
    await session.refresh(acc)
    return acc


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bank_account(account_id: str, session: AsyncSession = Depends(get_session)):
    acc = await session.get(BankAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Не знайдено")
    await session.delete(acc)
    await session.commit()
    return None
