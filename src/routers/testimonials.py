from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_permission
from ..models.models import Testimonial
from ..utils.redis_client import get_redis

router = APIRouter(prefix="/testimonials", tags=["Testimonials"])


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
class TestimonialCreate(BaseModel):
    nameKey: str = Field(..., min_length=1)
    roleKey: str = Field(..., min_length=1)
    quoteKey: str = Field(..., min_length=1)
    avatar: Optional[str] = None
    logo: Optional[str] = None
    rating: int = Field(default=5, ge=1, le=5)
    order: int = 0
    isVisible: bool = True


class TestimonialUpdate(BaseModel):
    nameKey: Optional[str] = Field(None, min_length=1)
    roleKey: Optional[str] = Field(None, min_length=1)
    quoteKey: Optional[str] = Field(None, min_length=1)
    avatar: Optional[str] = None
    logo: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    order: Optional[int] = None
    isVisible: Optional[bool] = None


class OrderItem(BaseModel):
    id: str
    order: int


class BulkOrderUpdate(BaseModel):
    items: List[OrderItem]


# ---------------------------------------------------------
# GET /testimonials
# ---------------------------------------------------------
@router.get("")
async def get_testimonials(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(Testimonial).order_by(Testimonial.order.asc(), Testimonial.id.asc())
    )
    return rows.scalars().all()


# ---------------------------------------------------------
# POST /testimonials
# ---------------------------------------------------------
@router.post("")
async def create_testimonial(
        payload: TestimonialCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("reviews", "create")),
):
    t = Testimonial(**payload.dict())
    session.add(t)
    await session.commit()
    await session.refresh(t)

    redis = get_redis()
    await redis.delete("testimonials")

    return {"status": "created", "testimonial": t}


# ---------------------------------------------------------
# PATCH /testimonials/{id}
# ---------------------------------------------------------
@router.patch("/{id}")
async def update_testimonial(
        id: str,
        payload: TestimonialUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("reviews", "update")),
):
    t = await session.get(Testimonial, id)
    if not t:
        api_error("NOT_FOUND", "Отзыв не найден", status=404)

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(t, k, v)

    await session.commit()
    await session.refresh(t)

    redis = get_redis()
    await redis.delete("testimonials")

    return {"status": "updated", "testimonial": t}


# ---------------------------------------------------------
# DELETE /testimonials/{id}
# ---------------------------------------------------------
@router.delete("/{id}")
async def delete_testimonial(
        id: str,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("reviews", "delete")),
):
    t = await session.get(Testimonial, id)
    if not t:
        api_error("NOT_FOUND", "Отзыв не найден", status=404)

    await session.delete(t)
    await session.commit()

    redis = get_redis()
    await redis.delete("testimonials")

    return {"status": "deleted"}


# ---------------------------------------------------------
# PATCH /testimonials/reorder
# ---------------------------------------------------------
@router.patch("/reorder")
async def reorder_testimonials(
        payload: BulkOrderUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("reviews", "update")),
):
    # Validate all IDs exist
    for item in payload.items:
        exists = await session.get(Testimonial, item.id)
        if not exists:
            api_error("NOT_FOUND", f"Отзыв с id={item.id} не найден", field="items", status=404)

    # Apply updates
    for item in payload.items:
        await session.execute(
            update(Testimonial)
            .where(Testimonial.id == item.id)
            .values(order=item.order)
        )

    await session.commit()

    redis = get_redis()
    await redis.delete("testimonials")

    return {"status": "reordered"}
