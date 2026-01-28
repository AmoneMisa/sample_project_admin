from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import FooterBlock, FooterItem
from ..utils.redis_client import get_redis

router = APIRouter(prefix="/footer", tags=["Footer"])

from pydantic import BaseModel
from typing import Optional, List


class FooterItemBase(BaseModel):
    type: str  # link, contact, logo, social, text
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
    type: Optional[str] = None
    labelKey: Optional[str] = None
    href: Optional[str] = None
    image: Optional[str] = None
    value: Optional[str] = None
    icon: Optional[str] = None
    order: Optional[int] = None
    isVisible: Optional[bool] = None


class FooterBlockBase(BaseModel):
    type: str  # menu, newsletter, logos, contacts, footerInfo
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


@router.get("")
async def list_footer(
        all: bool = False,
        session: AsyncSession = Depends(get_session)
):
    query = select(FooterBlock).order_by(FooterBlock.order.asc(), FooterBlock.id.asc())

    if not all:
        query = query.where(FooterBlock.isVisible == True)

    rows = await session.execute(query)
    blocks = rows.scalars().all()
    return blocks


@router.post("")
async def create_footer_block(
        payload: FooterBlockCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    block = FooterBlock(**payload.dict())
    session.add(block)
    await session.commit()
    await session.refresh(block)

    redis = get_redis()
    await redis.delete("footer")

    return block


@router.patch("/{id}")
async def update_footer_block(
        id: int,
        payload: FooterBlockUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    block = await session.get(FooterBlock, id)
    if not block:
        raise HTTPException(404, "Footer block not found")

    # Применяем изменения
    for k, v in payload.dict(exclude_unset=True).items():
        setattr(block, k, v)

    # Логика "только один видимый блок"
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

    return block


@router.delete("/{id}")
async def delete_footer_block(
        id: int,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    block = await session.get(FooterBlock, id)
    if not block:
        raise HTTPException(404, "Footer block not found")

    await session.delete(block)
    await session.commit()

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "deleted"}


@router.post("/{blockId}/items")
async def create_footer_item(
        blockId: int,
        payload: FooterItemCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    block = await session.get(FooterBlock, blockId)
    if not block:
        raise HTTPException(404, "Footer block not found")

    item = FooterItem(blockId=blockId, **payload.dict())
    session.add(item)
    await session.commit()
    await session.refresh(item)

    redis = get_redis()
    await redis.delete("footer")

    return item


@router.patch("/items/{id}")
async def update_footer_item(
        id: int,
        payload: FooterItemUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    item = await session.get(FooterItem, id)
    if not item:
        raise HTTPException(404, "Footer item not found")

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(item, k, v)

    await session.commit()
    await session.refresh(item)

    redis = get_redis()
    await redis.delete("footer")

    return item


@router.delete("/items/{id}")
async def delete_footer_item(
        id: int,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    item = await session.get(FooterItem, id)
    if not item:
        raise HTTPException(404, "Footer item not found")

    await session.delete(item)
    await session.commit()

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "deleted"}
