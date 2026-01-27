from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_permission
from ..models.models import Testimonial
from ..utils.redis_client import get_redis

router = APIRouter(prefix="/testimonials", tags=["Testimonials"])


# -----------------------------
#  Получить отзывы
# -----------------------------
@router.get("")
async def get_testimonials(
        session: AsyncSession = Depends(get_session),
):
    rows = await session.execute(
        select(Testimonial).order_by(Testimonial.order.asc(), Testimonial.id.asc())
    )
    return [row for row in rows.scalars().all()]


# -----------------------------
#  Создать отзыв
# -----------------------------
class TestimonialCreate(BaseModel):
    name: str
    role: str
    quote: str
    avatar: str | None = None
    logo: str | None = None
    rating: int = 5
    order: int = 0
    isVisible: bool = True


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

    # --- invalidate Redis cache ---
    redis = get_redis()
    await redis.delete("testimonials")

    return t


# -----------------------------
#  Обновить отзыв
# -----------------------------
class TestimonialUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    quote: str | None = None
    avatar: str | None = None
    logo: str | None = None
    rating: int | None = None
    order: int | None = None
    isVisible: bool | None = None


@router.patch("/{id}")
async def update_testimonial(
        id: int,
        payload: TestimonialUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("reviews", "update")),
):
    t = await session.get(Testimonial, id)
    if not t:
        raise HTTPException(404, "Testimonial not found")

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(t, k, v)

    await session.commit()

    # --- invalidate Redis cache ---
    redis = get_redis()
    await redis.delete("testimonials")

    return t


# -----------------------------
#  Удалить отзыв
# -----------------------------
@router.delete("/{id}")
async def delete_testimonial(
        id: int,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("reviews", "delete")),
):
    t = await session.get(Testimonial, id)
    if not t:
        raise HTTPException(404, "Testimonial not found")

    await session.delete(t)
    await session.commit()

    # --- invalidate Redis cache ---
    redis = get_redis()
    await redis.delete("testimonials")

    return {"status": "deleted"}


# -----------------------------
#  Массовая смена порядка
# -----------------------------
class OrderItem(BaseModel):
    id: int
    order: int

class BulkOrderUpdate(BaseModel):
    items: list[OrderItem]


@router.patch("/reorder")
async def reorder_testimonials(
        payload: BulkOrderUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_permission("reviews", "update")),
):
    for item in payload.items:
        await session.execute(
            update(Testimonial)
            .where(Testimonial.id == item.id)
            .values(order=item.order)
        )

    await session.commit()

    # --- invalidate Redis cache ---
    redis = get_redis()
    await redis.delete("testimonials")

    return {"status": "reordered"}
