import uuid
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import ServiceCategory

router = APIRouter(prefix="/service-categories", tags=["service-categories"])


class ServiceCategoryBase(BaseModel):
    id: UUID
    titleKey: str = Field(..., alias="titleKey")
    descriptionKey: str = Field(..., alias="descriptionKey")
    order: int
    isVisible: bool = Field(..., alias="isVisible")
    createdAt: datetime = Field(..., alias="createdAt")

    class Config:
        from_attributes = True
        validate_by_name = True


class ServiceCategoryCreate(BaseModel):
    titleKey: str
    descriptionKey: str
    order: int = 0
    isVisible: bool = True


class ServiceCategoryUpdate(BaseModel):
    titleKey: Optional[str] = None
    descriptionKey: Optional[str] = None
    order: Optional[int] = None
    isVisible: Optional[bool] = None


async def get_category_or_404(db: AsyncSession, category_id: UUID):
    result = await db.execute(
        select(ServiceCategory).where(ServiceCategory.id == str(category_id))
    )
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=404, detail="Service category not found")
    return cat


@router.get("", response_model=List[ServiceCategoryBase])
async def list_categories(db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(ServiceCategory).order_by(ServiceCategory.order.asc(), ServiceCategory.createdAt.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ServiceCategoryBase, status_code=201)
async def create_category(
        payload: ServiceCategoryCreate,
        db: AsyncSession = Depends(get_session),
        user=Depends(require_editor)
):
    cat = ServiceCategory(
        id=str(uuid.uuid4()),
        titleKey=payload.titleKey,
        descriptionKey=payload.descriptionKey,
        order=payload.order,
        isVisible=payload.isVisible,
    )
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


@router.patch("/{category_id}", response_model=ServiceCategoryBase)
async def update_category(
        category_id: UUID,
        payload: ServiceCategoryUpdate,
        db: AsyncSession = Depends(get_session),
        user=Depends(require_editor)
):
    cat = await get_category_or_404(db, category_id)

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(cat, field, value)

    await db.commit()
    await db.refresh(cat)
    return cat


@router.delete("/{category_id}", status_code=204)
async def delete_category(
        category_id: UUID,
        db: AsyncSession = Depends(get_session),
        user=Depends(require_editor)
):
    cat = await get_category_or_404(db, category_id)
    await db.delete(cat)
    await db.commit()