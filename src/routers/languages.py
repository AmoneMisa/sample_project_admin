from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from ..db.session import get_session
from ..deps.require_user import require_admin, require_editor
from ..models.models import Language

router = APIRouter(prefix="/languages", tags=["Languages"])


# -----------------------------
#  Получить все языки
# -----------------------------
@router.get("")
async def get_languages(
        session: AsyncSession = Depends(get_session),
):
    result = await session.scalars(select(Language))
    return result.all()


# -----------------------------
#  Получить включённые языки (ПУБЛИЧНО)
# -----------------------------
@router.get("/enabled")
async def get_enabled_languages(
        session: AsyncSession = Depends(get_session),
):
    result = await session.scalars(
        select(Language).where(Language.isEnabled.is_(True))
    )
    return result.all()


# -----------------------------
#  Инициализация языков (ТОЛЬКО АДМИН)
# -----------------------------
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
    return {"created": created}


# -----------------------------
#  Обновить язык (ADMIN или MODERATOR)
# -----------------------------
@router.patch("/{code}")
async def update_language(
        code: str,
        payload: dict,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),  # разрешаем admin и moderator
):
    lang = await session.scalar(select(Language).where(Language.code == code))
    if not lang:
        raise HTTPException(status_code=404, detail="Language not found")

    if "enabled" in payload:
        lang.isEnabled = bool(payload["enabled"])

    if "name" in payload:
        lang.name = payload["name"]

    await session.commit()
    return lang


class CreateLanguagePayload(BaseModel):
    code: str
    name: str
    enabled: bool = True


@router.post("")
async def create_language(
        payload: CreateLanguagePayload,
        session: AsyncSession = Depends(get_session),
        admin=Depends(require_admin),
):
    existing = await session.scalar(select(Language).where(Language.code == payload.code))
    if existing:
        raise HTTPException(status_code=400, detail="Language already exists")

    lang = Language(code=payload.code, name=payload.name, isEnabled=payload.enabled)
    session.add(lang)
    await session.commit()
    return lang
