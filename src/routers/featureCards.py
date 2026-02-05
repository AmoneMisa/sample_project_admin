import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import FeatureCard


router = APIRouter(prefix="/feature-cards", tags=["FeatureCards"])


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
class FeatureCardBase(BaseModel):
    image: Optional[str] = None
    titleKey: str = Field(..., min_length=1)
    descriptionKey: str = Field(..., min_length=1)
    order: int = 0
    isVisible: bool = True


class FeatureCardCreate(FeatureCardBase):
    pass


class FeatureCardUpdate(BaseModel):
    image: Optional[str] = None
    titleKey: Optional[str] = Field(None, min_length=1)
    descriptionKey: Optional[str] = Field(None, min_length=1)
    order: Optional[int] = None
    isVisible: Optional[bool] = None


# ---------------------------------------------------------
# GET /feature-cards
# ---------------------------------------------------------
@router.get("")
async def list_feature_cards(
        all: bool = False,
        session: AsyncSession = Depends(get_session)
):
    query = select(FeatureCard).order_by(FeatureCard.order.asc(), FeatureCard.id.asc())

    if not all:
        query = query.where(FeatureCard.isVisible == True)

    rows = await session.execute(query)
    return rows.scalars().all()


# ---------------------------------------------------------
# POST /feature-cards
# ---------------------------------------------------------
@router.post("")
async def create_feature_card(
        payload: FeatureCardCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    # Validation
    if not payload.titleKey.strip():
        api_error("INVALID_TITLE_KEY", "titleKey не может быть пустым", field="titleKey", status=422)

    if not payload.descriptionKey.strip():
        api_error("INVALID_DESCRIPTION_KEY", "descriptionKey не может быть пустым", field="descriptionKey", status=422)

    card = FeatureCard(
        id=str(uuid.uuid4()),
        **payload.dict()
    )

    session.add(card)
    await session.commit()
    await session.refresh(card)

    return {
        "status": "created",
        "card": card
    }


# ---------------------------------------------------------
# PATCH /feature-cards/{id}
# ---------------------------------------------------------
@router.patch("/{id}")
async def update_feature_card(
        id: str,
        payload: FeatureCardUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = await session.get(FeatureCard, id)
    if not card:
        api_error("FEATURE_CARD_NOT_FOUND", "FeatureCard не найден", status=404)

    # Field-level validation
    if payload.titleKey is not None and not payload.titleKey.strip():
        api_error("INVALID_TITLE_KEY", "titleKey не может быть пустым", field="titleKey", status=422)

    if payload.descriptionKey is not None and not payload.descriptionKey.strip():
        api_error("INVALID_DESCRIPTION_KEY", "descriptionKey не может быть пустым", field="descriptionKey", status=422)

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(card, k, v)

    await session.commit()
    await session.refresh(card)

    return {
        "status": "updated",
        "card": card
    }


# ---------------------------------------------------------
# DELETE /feature-cards/{id}
# ---------------------------------------------------------
@router.delete("/{id}")
async def delete_feature_card(
        id: str,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = await session.get(FeatureCard, id)
    if not card:
        api_error("FEATURE_CARD_NOT_FOUND", "FeatureCard не найден", status=404)

    await session.delete(card)
    await session.commit()

    return {"status": "deleted"}
