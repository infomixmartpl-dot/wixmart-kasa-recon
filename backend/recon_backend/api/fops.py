"""CRUD ФОПів."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Fop
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
