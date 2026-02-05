from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_admin, require_editor
from ..models.models import Language


router = APIRouter(prefix="/languages", tags=["Languages"])


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
class CreateLanguagePayload(BaseModel):
    code: str = Field(..., min_length=2)
    name: str = Field(..., min_length=1)
    enabled: bool = True


class UpdateLanguagePayload(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    enabled: Optional[bool] = None


# ---------------------------------------------------------
# GET /languages
# ---------------------------------------------------------
@router.get("")
async def get_languages(session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(Language))
    return result.all()


# ---------------------------------------------------------
# GET /languages/enabled
# ---------------------------------------------------------
@router.get("/enabled")
async def get_enabled_languages(session: AsyncSession = Depends(get_session)):
    result = await session.scalars(
        select(Language).where(Language.isEnabled.is_(True))
    )
    return result.all()


# ---------------------------------------------------------
# GET /languages/init  (admin only)
# ---------------------------------------------------------
@router.get("/init")
async def init_languages(
        session: AsyncSession = Depends(get_session),
        admin=Depends(require_admin),
):
    languages = [
        {"code": "ru", "name": "Russian"},
        {"code": "en", "name": "English"},
        {"code": "kk", "name": "Kazakh"},
    ]

    created = []

    for lang in languages:
        existing = await session.scalar(
            select(Language).where(Language.code == lang["code"])
        )

        if not existing:
            new_lang = Language(
                code=lang["code"],
                name=lang["name"],
                isEnabled=True
            )
            session.add(new_lang)
            await session.flush()
            created.append(lang["code"])

    await session.commit()
    return {"status": "initialized", "created": created}


# ---------------------------------------------------------
# PATCH /languages/{code}
# ---------------------------------------------------------
@router.patch("/{code}")
async def update_language(
        code: str,
        payload: UpdateLanguagePayload,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),  # admin + moderator
):
    lang = await session.scalar(select(Language).where(Language.code == code))
    if not lang:
        api_error("LANGUAGE_NOT_FOUND", "Язык не найден", status=404)

    if payload.name is not None and payload.name.strip() == "":
        api_error("INVALID_NAME", "Название языка не может быть пустым", field="name", status=422)

    if payload.enabled is not None:
        lang.isEnabled = payload.enabled

    if payload.name is not None:
        lang.name = payload.name

    await session.commit()
    await session.refresh(lang)

    return {"status": "updated", "language": lang}


# ---------------------------------------------------------
# POST /languages
# ---------------------------------------------------------
@router.post("")
async def create_language(
        payload: CreateLanguagePayload,
        session: AsyncSession = Depends(get_session),
        admin=Depends(require_admin),
):
    if payload.code.strip() == "":
        api_error("INVALID_CODE", "Код языка не может быть пустым", field="code", status=422)

    if payload.name.strip() == "":
        api_error("INVALID_NAME", "Название языка не может быть пустым", field="name", status=422)

    existing = await session.scalar(select(Language).where(Language.code == payload.code))
    if existing:
        api_error("LANGUAGE_EXISTS", "Язык уже существует", field="code", status=400)

    lang = Language(
        code=payload.code,
        name=payload.name,
        isEnabled=payload.enabled
    )

    session.add(lang)
    await session.commit()
    await session.refresh(lang)

    return {"status": "created", "language": lang}
