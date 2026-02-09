import uuid
from typing import Optional, Literal, List, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_editor
from ..models.models import Contact

router = APIRouter(prefix="/contacts", tags=["Contacts"])


# ---------------------------------------------------------
# Unified API error helper
# ---------------------------------------------------------
def api_error(
        code: str,
        message: str,
        status: int = 400,
        field: str | None = None,
        extra: dict | None = None,
):
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    if extra:
        detail["extra"] = extra
    raise HTTPException(status_code=status, detail=detail)


# ---------------------------------------------------------
# Schemas
# ---------------------------------------------------------
ContactType = Literal["phone", "email", "address", "social", "other"]


class ContactBase(BaseModel):
    id: Optional[str] = None
    type: ContactType = Field(..., min_length=1)
    labelKey: Optional[str] = None
    value: str = Field(..., min_length=1)
    order: int = 0
    isVisible: bool = True
    socialType: Optional[str] = None


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    type: Optional[ContactType] = Field(None, min_length=1)
    labelKey: Optional[str] = None
    value: Optional[str] = Field(None, min_length=1)
    order: Optional[int] = None
    isVisible: Optional[bool] = None
    socialType: Optional[str] = None


class ContactOut(BaseModel):
    # чтобы Pydantic мог читать поля из ORM-объекта SQLAlchemy
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: ContactType
    labelKey: Optional[str] = None
    socialType: Optional[str] = None
    value: str
    order: int = 0
    isVisible: bool = True


class ApiResponse(BaseModel):
    status: str
    description: str
    id: Optional[str] = None
    contact: Optional[ContactOut] = None
    contacts: Optional[List[ContactOut]] = None


# ---------------------------------------------------------
# Helpers (validation)
# ---------------------------------------------------------
def _validate_common(type_: Optional[str], value: Optional[str]):
    if type_ is not None and not type_.strip():
        api_error("INVALID_TYPE", "Поле type не может быть пустым", field="type", status=422)

    if value is not None and not value.strip():
        api_error("INVALID_VALUE", "Поле value не может быть пустым", field="value", status=422)


def _validate_social(type_: Optional[str], social_type: Optional[str]):
    # Если это соцсети — socialType обязателен
    if type_ == "social" and (social_type is None or not social_type.strip()):
        api_error("INVALID_SOCIAL_TYPE", "Для контакта типа social поле socialType обязательно", field="socialType", status=422)


# ---------------------------------------------------------
# GET /contacts
# ---------------------------------------------------------
@router.get("", response_model=ApiResponse)
async def list_contacts(
        all: bool = False,
        session: AsyncSession = Depends(get_session),
):
    query = select(Contact).order_by(Contact.order.asc(), Contact.id.asc())

    if not all:
        query = query.where(Contact.isVisible == True)

    rows = await session.execute(query)
    items = rows.scalars().all()

    return {
        "status": "ok",
        "description": "Список контактов",
        "contacts": items,
    }


# ---------------------------------------------------------
# POST /contacts
# ---------------------------------------------------------
@router.post("", response_model=ApiResponse)
async def create_contact(
        payload: ContactCreate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    _validate_common(payload.type, payload.value)
    _validate_social(payload.type, payload.socialType)

    new_id = payload.id or str(uuid.uuid4())

    # Защита от конфликта id (если клиент прислал уже существующий)
    exists = await session.get(Contact, new_id)
    if exists:
        api_error(
            "CONTACT_ID_EXISTS",
            "Контакт с таким id уже существует",
            status=409,
            field="id",
            extra={"id": new_id},
        )

    contact = Contact(id=new_id, **payload.dict(exclude={"id"}))

    session.add(contact)
    await session.commit()
    await session.refresh(contact)

    return {
        "status": "created",
        "description": "Контакт создан",
        "id": contact.id,
        "contact": contact,
    }


# ---------------------------------------------------------
# PATCH /contacts/{id}
# ---------------------------------------------------------
@router.patch("/{id}", response_model=ApiResponse)
async def update_contact(
        id: str,
        payload: ContactUpdate,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    contact = await session.get(Contact, id)
    if not contact:
        api_error("CONTACT_NOT_FOUND", "Контакт не найден", status=404)

    _validate_common(payload.type, payload.value)

    # Валидация socialType:
    # - если в payload пришёл type=social → требуем socialType
    # - если type не пришёл, но контакт уже social → требуем socialType, если его пытаются очистить
    next_type = payload.type if payload.type is not None else contact.type
    next_social = payload.socialType if payload.socialType is not None else contact.socialType
    _validate_social(next_type, next_social)

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(contact, k, v)

    await session.commit()
    await session.refresh(contact)

    return {
        "status": "updated",
        "description": "Контакт обновлён",
        "id": contact.id,
        "contact": contact,
    }


# ---------------------------------------------------------
# DELETE /contacts/{id}
# ---------------------------------------------------------
@router.delete("/{id}", response_model=ApiResponse)
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

    return {
        "status": "deleted",
        "description": "Контакт удалён",
        "id": id,
    }
