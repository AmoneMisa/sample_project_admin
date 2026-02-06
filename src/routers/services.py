import uuid
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..models.models import Service

router = APIRouter(prefix="/services", tags=["services"])


# -----------------------------
# Pydantic Schemas
# -----------------------------

class ServiceBase(BaseModel):
    id: UUID
    titleKey: str = Field(..., alias="titleKey")
    descriptionKey: str = Field(..., alias="descriptionKey")
    link: Optional[str]
    image: Optional[str]
    category: str
    order: int
    isVisible: bool = Field(..., alias="isVisible")
    createdAt: datetime = Field(..., alias="createdAt")

    class Config:
        from_attributes = True
        validate_by_name = True


class ServiceCreate(BaseModel):
    titleKey: str
    descriptionKey: str
    link: Optional[str]
    image: Optional[str]
    category: str
    order: int = 0
    isVisible: bool = True


class ServiceUpdate(BaseModel):
    titleKey: Optional[str]
    descriptionKey: Optional[str]
    link: Optional[str]
    image: Optional[str]
    category: Optional[str]
    order: Optional[int]
    isVisible: Optional[bool]


# -----------------------------
# Helpers
# -----------------------------

async def get_service_or_404(db: AsyncSession, service_id: UUID):
    result = await db.execute(
        select(Service).where(Service.id == str(service_id))
    )
    service = result.scalar_one_or_none()

    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    return service


# -----------------------------
# Routes
# -----------------------------

@router.get("", response_model=List[ServiceBase])
async def list_services(db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(Service).order_by(Service.order.asc(), Service.createdAt.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ServiceBase, status_code=201)
async def create_service(payload: ServiceCreate, db: AsyncSession = Depends(get_session)):
    service = Service(
        id=str(uuid.uuid4()),
        titleKey=payload.titleKey,
        descriptionKey=payload.descriptionKey,
        link=payload.link,
        image=payload.image,
        category=payload.category,
        order=payload.order,
        isVisible=payload.isVisible,
    )

    db.add(service)
    await db.commit()
    await db.refresh(service)

    return service


@router.patch("/{service_id}", response_model=ServiceBase)
async def update_service(service_id: UUID, payload: ServiceUpdate, db: AsyncSession = Depends(get_session)):
    service = await get_service_or_404(db, service_id)

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(service, field, value)

    await db.commit()
    await db.refresh(service)

    return service


@router.delete("/{service_id}", status_code=204)
async def delete_service(service_id: UUID, db: AsyncSession = Depends(get_session)):
    service = await get_service_or_404(db, service_id)

    await db.delete(service)
    await db.commit()
