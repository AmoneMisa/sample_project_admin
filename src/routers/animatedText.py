from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import AnimatedText
from ..utils.redis_client import get_redis

router = APIRouter(prefix="/animated-text", tags=["AnimatedText"])


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
class AnimatedTextCreate(BaseModel):
    titleKey: str = Field(..., min_length=1)
    isVisible: bool = True
    order: int = 0


class AnimatedTextUpdate(BaseModel):
    titleKey: Optional[str] = Field(None, min_length=1)
    isVisible: Optional[bool] = None
    order: Optional[int] = None


class OrderItem(BaseModel):
    id: str
    order: int


class BulkOrderUpdate(BaseModel):
    items: List[OrderItem]


# ---------------------------------------------------------
# GET /animated-text
# ---------------------------------------------------------
@router.get("")
async def get_animated_texts(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(AnimatedText).order_by(AnimatedText.order.asc(), AnimatedText.id.asc())
    )
    return rows.scalars().all()


# ---------------------------------------------------------
# POST /animated-text
# ---------------------------------------------------------
@router.post("")
async def create_animated_text(
        payload: AnimatedTextCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    item = AnimatedText(**payload.dict())
    session.add(item)
    await session.commit()
    await session.refresh(item)

    redis = get_redis()
    await redis.delete("animated_text")

    return {"status": "created", "animatedText": item}


# ---------------------------------------------------------
# PATCH /animated-text/{id}
# ---------------------------------------------------------
@router.patch("/{id}")
async def update_animated_text(
        id: str,
        payload: AnimatedTextUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    item = await session.get(AnimatedText, id)
    if not item:
        api_error("NOT_FOUND", "Animated text не найден", status=404)

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(item, k, v)

    await session.commit()
    await session.refresh(item)

    redis = get_redis()
    await redis.delete("animated_text")

    return {"status": "updated", "animatedText": item}


# ---------------------------------------------------------
# DELETE /animated-text/{id}
# ---------------------------------------------------------
@router.delete("/{id}")
async def delete_animated_text(
        id: str,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    item = await session.get(AnimatedText, id)
    if not item:
        api_error("NOT_FOUND", "Animated text не найден", status=404)

    await session.delete(item)
    await session.commit()

    redis = get_redis()
    await redis.delete("animated_text")

    return {"status": "deleted"}


# ---------------------------------------------------------
# PATCH /animated-text/reorder
# ---------------------------------------------------------
@router.patch("/reorder")
async def reorder_animated_texts(
        payload: BulkOrderUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    for it in payload.items:
        exists = await session.get(AnimatedText, it.id)
        if not exists:
            api_error("NOT_FOUND", f"Animated text с id={it.id} не найден", field="items", status=404)

    for it in payload.items:
        await session.execute(
            update(AnimatedText)
            .where(AnimatedText.id == it.id)
            .values(order=it.order)
        )

    await session.commit()

    redis = get_redis()
    await redis.delete("animated_text")

    return {"status": "reordered"}
