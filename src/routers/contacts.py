import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import Contact

router = APIRouter(prefix="/contacts", tags=["Contacts"])


class ContactBase(BaseModel):
    type: str
    label: Optional[str] = None  # translation key
    value: str
    order: int = 0
    isVisible: bool = True


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    type: Optional[str] = None
    label: Optional[str] = None
    value: Optional[str] = None
    order: Optional[int] = None
    isVisible: Optional[bool] = None


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


@router.post("")
async def create_contact(
        payload: ContactCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    contact = Contact(id=str(uuid.uuid4()), **payload.dict())
    session.add(contact)
    await session.commit()
    await session.refresh(contact)
    return contact


@router.patch("/{id}")
async def update_contact(
        id: str,
        payload: ContactUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    contact = await session.get(Contact, id)
    if not contact:
        raise HTTPException(404, "Contact not found")

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(contact, k, v)

    await session.commit()
    await session.refresh(contact)
    return contact


@router.delete("/{id}")
async def delete_contact(
        id: str,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    contact = await session.get(Contact, id)
    if not contact:
        raise HTTPException(404, "Contact not found")

    await session.delete(contact)
    await session.commit()
    return {"status": "deleted"}
