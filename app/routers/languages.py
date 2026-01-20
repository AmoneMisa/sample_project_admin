from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..models.models import Language

router = APIRouter(prefix="/languages", tags=["Languages"])


@router.get("/")
async def get_languages(session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(Language))
    return result.all()


@router.get("/enabled")
async def get_enabled_languages(
        session: AsyncSession = Depends(get_session)
):
    result = await session.scalars(
        select(Language).where(Language.isEnabled.is_(True))
    )
    return result.all()


@router.get("/init")
async def init_languages(session: AsyncSession = Depends(get_session)):
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
