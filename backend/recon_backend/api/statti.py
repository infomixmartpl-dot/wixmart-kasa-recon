"""CRUD статей руху коштів (read-only — заливаємо через sync-catalogs)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Stattia
from ..db.session import get_session

router = APIRouter()


class StattiaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name_1c: str
    movement_type: str | None = None
    odata_ref: str | None = None


@router.get("/", response_model=list[StattiaOut])
async def list_statti(
    fop_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Stattia).where(Stattia.fop_id == fop_id).order_by(Stattia.name_1c)
    )
    return result.scalars().all()
