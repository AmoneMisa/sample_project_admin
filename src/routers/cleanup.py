from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from ..db.session import get_session
from ..models.models import TranslationKey, TranslationValue
from ..deps.require_user import require_editor
import re

router = APIRouter(prefix="/cleanup", tags=["Maintenance"])

UUID_RE = r"[0-9a-fA-F-]{36}"

def is_broken_key(key: str, mode: str | None):
    if not key or key.strip() == "":
        return True

    if "undefined" in key:
        return True

    if key == "{}":
        return True

    if mode is None:
        return False

    if mode == "headerMenu":
        return not re.match(rf"^headerMenu\.{UUID_RE}\.", key)

    if mode == "contacts":
        return not re.match(rf"^contacts\.{UUID_RE}\.", key)

    if mode == "featureCard":
        return not re.match(rf"^featureCard\.{UUID_RE}\.", key)

    return False



@router.post("")
async def cleanup_translations(
        translations: int = 1,
        mode: str | None = None,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    result = await session.execute(select(TranslationKey))
    keys = result.scalars().all()

    broken_ids = [k.id for k in keys if is_broken_key(k.key, mode)]

    if not broken_ids:
        return {"removed": 0}

    await session.execute(
        delete(TranslationValue).where(
            TranslationValue.translationKeyId.in_(broken_ids)
        )
    )

    await session.execute(
        delete(TranslationKey).where(
            TranslationKey.id.in_(broken_ids)
        )
    )

    await session.commit()

    return {"removed": len(broken_ids)}
