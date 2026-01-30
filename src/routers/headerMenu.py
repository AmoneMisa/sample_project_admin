from typing import Any, List
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import HeaderMenu
from ..utils.redis_client import get_redis

router = APIRouter(prefix="/header-menu", tags=["header-menu"])


# ---------------------------------------------------------
# GET /header-menu
# ---------------------------------------------------------
@router.get("")
async def get_menu(
        session: AsyncSession = Depends(get_session)
):
    row = await session.execute(select(HeaderMenu))
    menu = row.scalars().first()
    return menu.json if menu else []


# ---------------------------------------------------------
# PATCH /header-menu
# ---------------------------------------------------------
class MenuUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    data: List[Any] = Field(alias="json")


@router.patch("")
async def update_menu(
        payload: MenuUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    # ищем единственную запись
    row = await session.execute(select(HeaderMenu))
    menu = row.scalars().first()

    if not menu:
        # создаём новую с UUID
        menu = HeaderMenu(json=payload.data)
        session.add(menu)
    else:
        menu.json = payload.data

    await session.commit()

    redis = get_redis()
    await redis.delete("header-menu")

    return menu.json
