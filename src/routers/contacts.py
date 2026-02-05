import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import Contact


router = APIRouter(prefix="/contacts", tags=["Contacts"])


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
class ContactBase(BaseModel):
    type: str = Field(..., min_length=1)
    label: Optional[str] = None  # translation key
    value: str = Field(..., min_length=1)
    order: int = 0
    isVisible: bool = True


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    type: Optional[str] = Field(None, min_length=1)
    label: Optional[str] = None
    value: Optional[str] = Field(None, min_length=1)
    order: Optional[int] = None
    isVisible: Optional[bool] = None


# ---------------------------------------------------------
# GET /contacts
# ---------------------------------------------------------
@router.get("")
async def list_contacts(
        all: bool = False,
        session: AsyncSession = Depends(get_session)
):
    query = select(Contact).order_by(Contact.order.asc(), Contact.id.asc())

    if not all:
        query = query.where(Contact.isVisible == True)

    rows = await session.execute(query)
    return rows.scalars().all()


# ---------------------------------------------------------
# POST /contacts
# ---------------------------------------------------------
@router.post("")
async def create_contact(
        payload: ContactCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    # Basic validation
    if not payload.type.strip():
        api_error("INVALID_TYPE", "Поле type не может быть пустым", field="type", status=422)

    if not payload.value.strip():
        api_error("INVALID_VALUE", "Поле value не может быть пустым", field="value", status=422)

    contact = Contact(
        id=str(uuid.uuid4()),
        **payload.dict()
    )

    session.add(contact)
    await session.commit()
    await session.refresh(contact)

    return {
        "status": "created",
        "contact": contact
    }


# ---------------------------------------------------------
# PATCH /contacts/{id}
# ---------------------------------------------------------
@router.patch("/{id}")
async def update_contact(
        id: str,
        payload: ContactUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    contact = await session.get(Contact, id)
    if not contact:
        api_error("CONTACT_NOT_FOUND", "Контакт не найден", status=404)

    # Field-level validation
    if payload.type is not None and not payload.type.strip():
        api_error("INVALID_TYPE", "Поле type не может быть пустым", field="type", status=422)

    if payload.value is not None and not payload.value.strip():
        api_error("INVALID_VALUE", "Поле value не может быть пустым", field="value", status=422)

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(contact, k, v)

    await session.commit()
    await session.refresh(contact)

    return {
        "status": "updated",
        "contact": contact
    }


# ---------------------------------------------------------
# DELETE /contacts/{id}
# ---------------------------------------------------------
@router.delete("/{id}")
async def delete_contact(
        id: str,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    contact = await session.get(Contact, id)
    if not contact:
        api_error("CONTACT_NOT_FOUND", "Контакт не найден", status=404)

    await session.delete(contact)
    await session.commit()

    return {"status": "deleted"}
