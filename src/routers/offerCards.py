from decimal import Decimal
from typing import List, Optional

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
class FeatureItem(BaseModel):
    id: str = Field(..., min_length=36, max_length=36)
    labelKey: str = Field(..., min_length=1)
    order: int = Field(ge=0)
    isVisible: bool = True


class OfferCardCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    monthly: condecimal(ge=Decimal("0.01"), decimal_places=2)
    yearly: condecimal(ge=Decimal("0.01"), decimal_places=2)
    features: List[FeatureItem] = Field(..., min_length=1)
    highlight: bool = False
    order: int = 0
    isVisible: bool = True


class FeatureItemUpdate(BaseModel):
    id: str = Field(..., min_length=36, max_length=36)
    labelKey: str = Field(..., min_length=1)
    order: int = Field(ge=0)
    isVisible: bool = True


class OfferCardUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = Field(None, min_length=1)
    monthly: Optional[condecimal(ge=Decimal("0.01"), decimal_places=2)] = None
    yearly: Optional[condecimal(ge=Decimal("0.01"), decimal_places=2)] = None
    features: Optional[List[FeatureItemUpdate]] = None
    highlight: Optional[bool] = None
    order: Optional[int] = None
    isVisible: Optional[bool] = None


# ---------------------------------------------------------
# GET /offer-cards
# ---------------------------------------------------------
@router.get("")
async def list_offer_cards(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(OfferCard).order_by(OfferCard.order.asc(), OfferCard.id.asc())
    )
    return rows.scalars().all()


# ---------------------------------------------------------
# POST /offer-cards
# ---------------------------------------------------------
@router.post("")
async def create_offer_card(
        payload: OfferCardCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    # Validation
    if not payload.features:
        api_error("NO_FEATURES", "Добавьте хотя бы одну фичу", field="features", status=422)

    card = OfferCard(**payload.dict())
    session.add(card)

    try:
        await session.commit()
    except IntegrityError as exc:
        api_error("DB_ERROR", "Ошибка базы данных", status=400, field=None)

    await session.refresh(card)

    redis = get_redis()
    await redis.delete("offer-cards")

    return {"status": "created", "card": card}


# ---------------------------------------------------------
# PATCH /offer-cards/{id}
# ---------------------------------------------------------
@router.patch("/{id}")
async def update_offer_card(
        id: str,
        payload: OfferCardUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = await session.get(OfferCard, id)
    if not card:
        api_error("NOT_FOUND", "Карточка не найдена", field="id", status=404)

    # Validate features
    if payload.features:
        for f in payload.features:
            if not f.labelKey.strip():
                api_error("INVALID_LABEL_KEY", "labelKey обязателен", field="features.labelKey", status=422)

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(card, k, v)

    try:
        await session.commit()
    except IntegrityError:
        api_error("DB_ERROR", "Ошибка базы данных", status=400)

    await session.refresh(card)

    redis = get_redis()
    await redis.delete("offer-cards")

    return {"status": "updated", "card": card}


# ---------------------------------------------------------
# DELETE /offer-cards/{id}
# ---------------------------------------------------------
@router.delete("/{id}")
async def delete_offer_card(
        id: str,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = await session.get(OfferCard, id)
    if not card:
        api_error("NOT_FOUND", "Карточка не найдена", status=404)

    await session.delete(card)
    await session.commit()

    redis = get_redis()
    await redis.delete("offer-cards")

    return {"status": "deleted"}
