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

    data: List[Any] | None = Field(default=None, alias="json")
    delete_all: bool = Field(default=False, alias="deleteAll")


@router.patch("")
async def update_menu(
        payload: MenuUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    row = await session.execute(select(HeaderMenu))
    menu = row.scalars().first()

    if not menu:
        menu = HeaderMenu(json=payload.data)
        session.add(menu)
    else:
        # только замена списка
        menu.json = payload.data

    await session.commit()

    redis = get_redis()
    await redis.delete("header-menu")

    return menu.json


@router.post("")
async def add_menu_item(
        item: dict,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    row = await session.execute(select(HeaderMenu))
    menu = row.scalars().first()

    if not menu:
        menu = HeaderMenu(json=[item])
        session.add(menu)
    else:
        menu.json.append(item)

    await session.commit()

    redis = get_redis()
    await redis.delete("header-menu")

    return item


from fastapi import Query


@router.delete("")
async def delete_menu(
        id: str | None = None,
        delete_all: bool = Query(default=False, alias="deleteAll"),
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    row = await session.execute(select(HeaderMenu))
    menu = row.scalars().first()

    if not menu:
        return []

    if delete_all:
        menu.json = []
    else:
        if id is not None:
            menu.json = [item for item in menu.json if item.get("id") != id]

    await session.commit()

    redis = get_redis()
    await redis.delete("header-menu")

    return menu.json
