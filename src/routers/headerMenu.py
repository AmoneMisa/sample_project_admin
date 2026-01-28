from typing import Any, List
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

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
    row = await session.get(HeaderMenu, 1)
    return row.json if row else []


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
    row = await session.get(HeaderMenu, 1)

    if not row:
        row = HeaderMenu(id=1, json=payload.data)
        session.add(row)
    else:
        row.json = payload.data

    await session.commit()

    redis = get_redis()
    await redis.delete("header-menu")

    return row.json
