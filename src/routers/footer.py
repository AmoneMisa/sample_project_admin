from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import FooterMenuBlock, FooterMenuLink
from ..utils.redis_client import get_redis


router = APIRouter(prefix="/footer/menu", tags=["FooterMenu"])


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def api_error(code: str, message: str, status: int = 400, field: str | None = None):
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    raise HTTPException(status_code=status, detail=detail)


# -------------------------------------------------
# Schemas
# -------------------------------------------------
class MenuLinkDTO(BaseModel):
    id: str = Field(..., min_length=1)
    labelKey: str = Field(..., min_length=1)
    href: str = Field(..., min_length=1)
    order: int = 0
    isVisible: bool = True


class MenuBlockDTO(BaseModel):
    id: str = Field(..., min_length=1)
    titleKey: str = Field(..., min_length=1)
    order: int = 0
    isVisible: bool = True
    links: List[MenuLinkDTO] = []


class BlocksPayload(BaseModel):
    blocks: List[MenuBlockDTO]


class DeletePayload(BaseModel):
    ids: List[str]


# -------------------------------------------------
# GET
# -------------------------------------------------
@router.get("/blocks")
async def list_blocks(
        all: bool = False,
        session: AsyncSession = Depends(get_session),
):
    q = (
        select(FooterMenuBlock)
        .options(selectinload(FooterMenuBlock.links))
        .order_by(FooterMenuBlock.order.asc(), FooterMenuBlock.id.asc())
    )

    if not all:
        q = q.where(FooterMenuBlock.isVisible == True)

    rows = await session.execute(q)
    return rows.scalars().all()


# -------------------------------------------------
# POST (create many)
# -------------------------------------------------
@router.post("/blocks")
async def create_blocks(
        payload: BlocksPayload,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    seen_ids = set()

    for b in payload.blocks:
        if b.id in seen_ids:
            api_error("DUPLICATE_ID", f"Duplicate id: {b.id}", 422)

        seen_ids.add(b.id)

        block = FooterMenuBlock(
            id=b.id,
            titleKey=b.titleKey,
            order=b.order,
            isVisible=b.isVisible,
        )

        block.links = [
            FooterMenuLink(
                id=l.id,
                blockId=b.id,
                labelKey=l.labelKey,
                href=l.href,
                order=l.order,
                isVisible=l.isVisible,
            )
            for l in b.links
        ]

        session.add(block)

    await session.commit()

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "created", "count": len(payload.blocks)}


# -------------------------------------------------
# PATCH (update many)
# -------------------------------------------------
@router.patch("/blocks")
async def update_blocks(
        payload: BlocksPayload,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    ids = [b.id for b in payload.blocks]

    rows = await session.execute(
        select(FooterMenuBlock)
        .where(FooterMenuBlock.id.in_(ids))
        .options(selectinload(FooterMenuBlock.links))
    )

    blocks_map = {b.id: b for b in rows.scalars().all()}

    for dto in payload.blocks:
        block = blocks_map.get(dto.id)

        if not block:
            api_error("BLOCK_NOT_FOUND", f"Not found: {dto.id}", 404)

        # block fields
        block.titleKey = dto.titleKey
        block.order = dto.order
        block.isVisible = dto.isVisible

        # links
        existing = {l.id: l for l in block.links}
        incoming_ids = set()

        for l in dto.links:
            incoming_ids.add(l.id)

            cur = existing.get(l.id)

            if cur:
                cur.labelKey = l.labelKey
                cur.href = l.href
                cur.order = l.order
                cur.isVisible = l.isVisible
            else:
                block.links.append(
                    FooterMenuLink(
                        id=l.id,
                        blockId=block.id,
                        labelKey=l.labelKey,
                        href=l.href,
                        order=l.order,
                        isVisible=l.isVisible,
                    )
                )

        # remove deleted links
        block.links = [l for l in block.links if l.id in incoming_ids]

    await session.commit()

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "updated", "count": len(payload.blocks)}


# -------------------------------------------------
# DELETE (delete many)
# -------------------------------------------------
@router.delete("/blocks")
async def delete_blocks(
        payload: DeletePayload,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    rows = await session.execute(
        select(FooterMenuBlock).where(FooterMenuBlock.id.in_(payload.ids))
    )

    blocks = rows.scalars().all()

    found = {b.id for b in blocks}
    missing = [i for i in payload.ids if i not in found]

    if missing:
        api_error("BLOCK_NOT_FOUND", f"Missing: {', '.join(missing)}", 404)

    for b in blocks:
        await session.delete(b)

    await session.commit()

    redis = get_redis()
    await redis.delete("footer")

    return {"status": "deleted", "count": len(payload.ids)}
