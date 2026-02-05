from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, condecimal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
from typing import List


class FeatureItem(BaseModel):
    labelKey: str | None = None
    order: int = Field(ge=0)
    isVisible: bool = True


class OfferCardCreate(BaseModel):
    name: str
    description: str
    monthly: condecimal(ge=Decimal("0.01"), decimal_places=2)
    yearly: condecimal(ge=Decimal("0.01"), decimal_places=2)
    features: List[FeatureItem] = []
    highlight: bool = False
    order: int = 0
    isVisible: bool = True


@router.post("")
async def create_offer_card(
        payload: OfferCardCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    # Валидация
    if payload.monthly < Decimal("0.01"):
        raise HTTPException(
            422,
            detail={"field": "monthly", "message": "Минимальная стоимость — 0.01"}
        )

    if payload.yearly < Decimal("0.01"):
        raise HTTPException(
            422,
            detail={"field": "yearly", "message": "Минимальная стоимость — 0.01"}
        )

    if not payload.features:
        raise HTTPException(
            422,
            detail={"field": "features", "message": "Добавьте хотя бы одну фичу"}
        )

    card = OfferCard(**payload.dict())

    session.add(card)

    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(
            400,
            detail={"message": "Ошибка базы данных", "error": str(exc.orig)}
        )

    await session.refresh(card)

    redis = get_redis()
    await redis.delete("offer-cards")

    return card


# ---------------------------------------------------------
# PATCH /offer-cards/{id}
# ---------------------------------------------------------
class FeatureItemUpdate(BaseModel):
    labelKey: str = Field(..., min_length=1, max_length=255)
    order: int = Field(ge=0)
    isVisible: bool = True


class OfferCardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    monthly: condecimal(ge=Decimal("0.01"), decimal_places=2) | None = None
    yearly: condecimal(ge=Decimal("0.01"), decimal_places=2) | None = None
    features: list[FeatureItemUpdate] | None = None
    highlight: bool | None = None
    order: int | None = None
    isVisible: bool | None = None


@router.patch("/{id}")
async def update_offer_card(
        id: str,
        payload: OfferCardUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = await session.get(OfferCard, id)
    if not card:
        raise HTTPException(
            404,
            detail={"field": "id", "message": "Карточка не найдена"}
        )

    # Проверяем фичи
    if payload.features:
        for f in payload.features:
            if not f.labelKey:
                raise HTTPException(
                    422,
                    detail={"field": "features.labelKey", "message": "labelKey обязателен"}
                )

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(card, k, v)

    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(
            400,
            detail={"message": "Ошибка базы данных", "error": str(exc.orig)}
        )

    await session.refresh(card)

    redis = get_redis()
    await redis.delete("offer-cards")

    return card


# ---------------------------------------------------------
# DELETE /offer-cards/{id}
# ---------------------------------------------------------
@router.delete("/{id}")
async def delete_offer_card(
        id: str,  # UUID
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
