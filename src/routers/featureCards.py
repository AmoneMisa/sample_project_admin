from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import FeatureCard

router = APIRouter(prefix="/feature-cards", tags=["FeatureCards"])

from pydantic import BaseModel
from typing import Optional


class FeatureCardBase(BaseModel):
    image: Optional[str] = None
    titleKey: str
    descriptionKey: str
    order: int = 0
    isVisible: bool = True


class FeatureCardCreate(FeatureCardBase):
    pass


class FeatureCardUpdate(BaseModel):
    image: Optional[str] = None
    titleKey: Optional[str] = None
    descriptionKey: Optional[str] = None
    order: Optional[int] = None
    isVisible: Optional[bool] = None


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


@router.post("")
async def create_feature_card(
        payload: FeatureCardCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = FeatureCard(**payload.dict())
    session.add(card)
    await session.commit()
    await session.refresh(card)
    return card


@router.patch("/{id}")
async def update_feature_card(
        id: int,
        payload: FeatureCardUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = await session.get(FeatureCard, id)
    if not card:
        raise HTTPException(404, "FeatureCard not found")

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(card, k, v)

    await session.commit()
    await session.refresh(card)
    return card


@router.delete("/{id}")
async def delete_feature_card(
        id: int,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    card = await session.get(FeatureCard, id)
    if not card:
        raise HTTPException(404, "FeatureCard not found")

    await session.delete(card)
    await session.commit()
    return {"status": "deleted"}
