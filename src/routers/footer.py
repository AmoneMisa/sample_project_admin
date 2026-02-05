import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import FooterBlock, FooterItem
from ..utils.redis_client import get_redis


router = APIRouter(prefix="/footer", tags=["Footer"])


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
class FooterItemBase(BaseModel):
    type: str = Field(..., min_length=1)
    labelKey: Optional[str] = None
    href: Optional[str] = None
    image: Optional[str] = None
    value: Optional[str] = None
    icon: Optional[str] = None
    order: int = 0
    isVisible: bool = True


class FooterItemCreate(FooterItemBase):
    pass


class FooterItemUpdate(BaseModel):
    type: Optional[str] = Field(None, min_length=1)
    labelKey: Optional[str] = None
    href: Optional[str] = None
    image: Optional[str] = None
    value: Optional[str] = None
    icon: Optional[str] = None
    order: Optional[int] = None
    isVisible: Optional[bool] = None


class FooterBlockBase(BaseModel):
    type: str = Field(..., min_length=1)
    titleKey: Optional[str] = None
    descriptionKey: Optional[str] = None
    allowedDomains: Optional[List[str]] = None
    order: int = 0
    isVisible: bool = True


class FooterBlockCreate(FooterBlockBase):
    pass


class FooterBlockUpdate(BaseModel):
    titleKey: Optional[str] = None
    descriptionKey: Optional[str] = None
    allowedDomains: Optional[List[str]] = None
    order: Optional[int] = None
    isVisible: Optional[bool] = None


# ---------------------------------------------------------
# LIST BLOCKS
# ---------------------------------------------------------
@router.get("")
async def list_footer(
        all: bool = False,
        session: AsyncSession = Depends(get_session)
):
    query = select(FooterBlock).order_by(FooterBlock.order.asc(), FooterBlock.id.asc())

    if not all:
        query = query.where(FooterBlock.isVisible == True)

    rows = await session.execute(query)
    return rows.scalars().all()


# ---------------------------------------------------------
# CREATE BLOCK
# ---------------------------------------------------------
@router.post("")
async def create_footer_block(
        payload: FooterBlockCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    if not payload.type.strip():
        api_error("INVALID_TYPE", "Поле type не может быть пустым", field="type", status=422)

    block = FooterBlock(
        id=str(uuid.uuid4()),
        **payload.dict()
    )

    session.add(block)
    await session.commit()
    await session.refresh(block)

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "created", "block": block}


# ---------------------------------------------------------
# UPDATE BLOCK
# ---------------------------------------------------------
@router.patch("/{id}")
async def update_footer_block(
        id: str,
        payload: FooterBlockUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    block = await session.get(FooterBlock, id)
    if not block:
        api_error("BLOCK_NOT_FOUND", "Footer block не найден", status=404)

    if payload.titleKey is not None and payload.titleKey.strip() == "":
        api_error("INVALID_TITLE_KEY", "titleKey не может быть пустым", field="titleKey", status=422)

    if payload.descriptionKey is not None and payload.descriptionKey.strip() == "":
        api_error("INVALID_DESCRIPTION_KEY", "descriptionKey не может быть пустым", field="descriptionKey", status=422)

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(block, k, v)

    # Only one visible block of certain types
    if payload.isVisible is True:
        if block.type in ("contacts", "logos", "newsletter"):
            await session.execute(
                update(FooterBlock)
                .where(FooterBlock.type == block.type, FooterBlock.id != block.id)
                .values(isVisible=False)
            )

    await session.commit()
    await session.refresh(block)

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "updated", "block": block}


# ---------------------------------------------------------
# DELETE BLOCK
# ---------------------------------------------------------
@router.delete("/{id}")
async def delete_footer_block(
        id: str,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    block = await session.get(FooterBlock, id)
    if not block:
        api_error("BLOCK_NOT_FOUND", "Footer block не найден", status=404)

    await session.delete(block)
    await session.commit()

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "deleted"}


# ---------------------------------------------------------
# CREATE ITEM
# ---------------------------------------------------------
@router.post("/{blockId}/items")
async def create_footer_item(
        blockId: str,
        payload: FooterItemCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    block = await session.get(FooterBlock, blockId)
    if not block:
        api_error("BLOCK_NOT_FOUND", "Footer block не найден", status=404)

    if not payload.type.strip():
        api_error("INVALID_TYPE", "Поле type не может быть пустым", field="type", status=422)

    item = FooterItem(
        id=str(uuid.uuid4()),
        blockId=blockId,
        **payload.dict()
    )

    session.add(item)
    await session.commit()
    await session.refresh(item)

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "created", "item": item}


# ---------------------------------------------------------
# UPDATE ITEM
# ---------------------------------------------------------
@router.patch("/items/{id}")
async def update_footer_item(
        id: str,
        payload: FooterItemUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    item = await session.get(FooterItem, id)
    if not item:
        api_error("ITEM_NOT_FOUND", "Footer item не найден", status=404)

    if payload.type is not None and payload.type.strip() == "":
        api_error("INVALID_TYPE", "Поле type не может быть пустым", field="type", status=422)

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(item, k, v)

    await session.commit()
    await session.refresh(item)

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "updated", "item": item}


# ---------------------------------------------------------
# DELETE ITEM
# ---------------------------------------------------------
@router.delete("/items/{id}")
async def delete_footer_item(
        id: str,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    item = await session.get(FooterItem, id)
    if not item:
        api_error("ITEM_NOT_FOUND", "Footer item не найден", status=404)

    await session.delete(item)
    await session.commit()

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "deleted"}


# ---------------------------------------------------------
# LIST ITEMS
# ---------------------------------------------------------
@router.get("/{blockId}/items")
async def list_footer_items(
        blockId: str,
        session: AsyncSession = Depends(get_session)
):
    rows = await session.execute(
        select(FooterItem)
        .where(FooterItem.blockId == blockId)
        .order_by(FooterItem.order.asc())
    )
    return rows.scalars().all()
