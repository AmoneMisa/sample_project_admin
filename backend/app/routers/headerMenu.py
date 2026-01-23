from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ConfigDict, Field

from ..db.session import get_session
from ..models.models import HeaderMenu

router = APIRouter(prefix="/header-menu", tags=["header-menu"])

@router.get("")
async def get_menu(session: AsyncSession = Depends(get_session)):
    row = await session.get(HeaderMenu, 1)
    return row.json if row else []


from typing import Any, List

class MenuUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: List[Any] = Field(alias="json")


@router.patch("")
async def update_menu(payload: MenuUpdate, session: AsyncSession = Depends(get_session)):
    row = await session.get(HeaderMenu, 1)
    if not row:
        row = HeaderMenu(id=1, json=payload.data)
        session.add(row)
    else:
        row.json = payload.data

    await session.commit()
    return row.json
