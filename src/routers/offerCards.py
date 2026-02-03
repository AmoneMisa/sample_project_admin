from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import OfferCard
from ..utils.redis_client import get_redis

router = APIRouter(prefix="/offer-cards", tags=["OfferCards"])


# ---------------------------------------------------------
# GET /offer-cards
# ---------------------------------------------------------
@router.get("")
async def list_offer_cards(
        session: AsyncSession = Depends(get_session)
):
    rows = await session.execute(
        select(OfferCard).order_by(OfferCard.order.asc(), OfferCard.id.asc())
    )
    return rows.scalars().all()


# ---------------------------------------------------------
# POST /offer-cards
# ---------------------------------------------------------
class OfferCardCreate(BaseModel):
    key: str
    name: str
    description: str
    monthly: str
    yearly: str
    features: str
    highlight: bool = False
    order: int = 0
    isVisible: bool = True


@router.post("")
async def create_offer_card(
        payload: OfferCardCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = OfferCard(**payload.dict())
    session.add(card)
    await session.commit()
    await session.refresh(card)

    redis = get_redis()
    await redis.delete("offer-cards")

    return card


# ---------------------------------------------------------
# PATCH /offer-cards/{id}
# ---------------------------------------------------------
class OfferCardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    monthly: str | None = None
    yearly: str | None = None
    features: str | None = None
    highlight: bool | None = None
    order: int | None = None
    isVisible: bool | None = None


@router.patch("/{id}")
async def update_offer_card(
        id: str,   # UUID
        payload: OfferCardUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = await session.get(OfferCard, id)
    if not card:
        raise HTTPException(404, "OfferCard not found")

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(card, k, v)

    await session.commit()
    await session.refresh(card)

    redis = get_redis()
    await redis.delete("offer-cards")

    return card


# ---------------------------------------------------------
# DELETE /offer-cards/{id}
# ---------------------------------------------------------
@router.delete("/{id}")
async def delete_offer_card(
        id: str,   # UUID
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = await session.get(OfferCard, id)
    if not card:
        raise HTTPException(404, "OfferCard not found")

    await session.delete(card)
    await session.commit()

    redis = get_redis()
    await redis.delete("offer-cards")

    return {"status": "deleted"}
