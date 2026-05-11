"""CRUD підрозділів."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Fop, Pidrozdil
from ..db.session import get_session
from .schemas import PidrozdilCreate, PidrozdilOut

router = APIRouter()


@router.get("/", response_model=list[PidrozdilOut])
async def list_pidrozdily(
    fop_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Pidrozdil).where(Pidrozdil.fop_id == fop_id).order_by(Pidrozdil.name_1c))
    return result.scalars().all()


@router.post("/", response_model=PidrozdilOut, status_code=status.HTTP_201_CREATED)
async def create_pidrozdil(
    fop_id: str = Query(...),
    payload: PidrozdilCreate = ...,
    session: AsyncSession = Depends(get_session),
):
    fop = await session.get(Fop, fop_id)
    if not fop:
        raise HTTPException(status_code=404, detail="ФОП не знайдено")
    p = Pidrozdil(fop_id=fop_id, **payload.model_dump())
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


@router.delete("/{pidrozdil_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pidrozdil(pidrozdil_id: str, session: AsyncSession = Depends(get_session)):
    p = await session.get(Pidrozdil, pidrozdil_id)
    if not p:
        raise HTTPException(status_code=404, detail="Не знайдено")
    await session.delete(p)
    await session.commit()
    return None
