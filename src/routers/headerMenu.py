from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import HeaderMenu
from ..utils.redis_client import get_redis


router = APIRouter(prefix="/header-menu", tags=["header-menu"])


# ---------------------------------------------------------
# Unified API error helper
# ---------------------------------------------------------
def api_error(code: str, message: str, status: int = 400, field: str | None = None):
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    raise HTTPException(status_code=status, detail=detail)


# ---------------------------------------------------------
# Schemas
# ---------------------------------------------------------
class MenuUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: Optional[List[Any]] = Field(default=None, alias="json")
    delete_all: bool = Field(default=False, alias="deleteAll")


class MenuItem(BaseModel):
    id: Optional[str] = None
    labelKey: Optional[str] = None
    href: Optional[str] = None
    icon: Optional[str] = None
    order: int = 0
    isVisible: bool = True


# ---------------------------------------------------------
# GET /header-menu
# ---------------------------------------------------------
@router.get("")
async def get_menu(session: AsyncSession = Depends(get_session)):
    row = await session.execute(select(HeaderMenu))
    menu = row.scalars().first()
    return menu.json if menu else []


# ---------------------------------------------------------
# PATCH /header-menu
# ---------------------------------------------------------
@router.patch("")
async def update_menu(
        payload: MenuUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    # Validate payload
    if payload.delete_all and payload.data:
        api_error(
            "INVALID_REQUEST",
            "Нельзя одновременно передать deleteAll=true и json",
            status=422
        )

    row = await session.execute(select(HeaderMenu))
    menu = row.scalars().first()

    if payload.delete_all:
        new_data = []
    else:
        new_data = payload.data or []

        # Validate items
        for idx, item in enumerate(new_data):
            if not isinstance(item, dict):
                api_error(
                    "INVALID_ITEM",
                    f"Элемент меню #{idx} должен быть объектом",
                    field=f"json[{idx}]",
                    status=422
                )

    if not menu:
        menu = HeaderMenu(json=new_data)
        session.add(menu)
    else:
        menu.json = new_data

    await session.commit()

    redis = get_redis()
    await redis.delete("header-menu")

    return {"status": "updated", "menu": menu.json}


# ---------------------------------------------------------
# POST /header-menu
# ---------------------------------------------------------
@router.post("")
async def add_menu_item(
        item: dict,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    # Validate item
    if not isinstance(item, dict):
        api_error("INVALID_ITEM", "Элемент меню должен быть объектом", status=422)

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

    return {"status": "created", "item": item}


# ---------------------------------------------------------
# DELETE /header-menu
# ---------------------------------------------------------
@router.delete("")
async def delete_menu(
        id: Optional[str] = None,
        delete_all: bool = Query(default=False, alias="deleteAll"),
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    row = await session.execute(select(HeaderMenu))
    menu = row.scalars().first()

    if not menu:
        return {"status": "empty", "menu": []}

    if delete_all:
        menu.json = []
    else:
        if id is None:
            api_error("MISSING_ID", "Не указан id элемента для удаления", field="id", status=422)

        before = len(menu.json)
        menu.json = [item for item in menu.json if item.get("id") != id]
        after = len(menu.json)

        if before == after:
            api_error("ITEM_NOT_FOUND", f"Элемент с id={id} не найден", status=404)

    await session.commit()

    redis = get_redis()
    await redis.delete("header-menu")

    return {"status": "updated", "menu": menu.json}
