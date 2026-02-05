from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
import re

from ..db.session import get_session
from ..models.models import TranslationKey, TranslationValue
from ..deps.require_user import require_editor


router = APIRouter(prefix="/cleanup", tags=["Maintenance"])

UUID_RE = r"[0-9a-fA-F-]{36}"


# ---------------------------------------------------------
# Unified API error helper
# ---------------------------------------------------------
def api_error(code: str, message: str, status: int = 400, field: str | None = None):
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    from fastapi import HTTPException
    raise HTTPException(status_code=status, detail=detail)


# ---------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------
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


# ---------------------------------------------------------
# Request model
# ---------------------------------------------------------
class CleanupRequest(BaseModel):
    translations: int = 1
    mode: str | None = None


# ---------------------------------------------------------
# POST /cleanup
# ---------------------------------------------------------
@router.post("")
async def cleanup_translations(
        data: CleanupRequest,
        session: AsyncSession = Depends(get_session),
        user=Depends(require_editor),
):
    # Validate mode
    allowed_modes = {None, "headerMenu", "contacts", "featureCard"}
    if data.mode not in allowed_modes:
        api_error(
            "INVALID_MODE",
            f"Недопустимый режим очистки: {data.mode}. "
            f"Разрешено: headerMenu, contacts, featureCard или null",
            field="mode",
            status=422,
        )

    # Validate translations count
    if data.translations < 1:
        api_error(
            "INVALID_COUNT",
            "Количество должно быть >= 1",
            field="translations",
            status=422,
        )

    # Load all keys
    result = await session.execute(select(TranslationKey))
    keys = result.scalars().all()

    if not keys:
        return {"removed": 0, "status": "no_keys_found"}

    # Detect broken keys
    broken_ids = [k.id for k in keys if is_broken_key(k.key, data.mode)]

    if not broken_ids:
        return {"removed": 0, "status": "nothing_to_cleanup"}

    # Delete values
    await session.execute(
        delete(TranslationValue).where(
            TranslationValue.translationKeyId.in_(broken_ids)
        )
    )

    # Delete keys
    await session.execute(
        delete(TranslationKey).where(
            TranslationKey.id.in_(broken_ids)
        )
    )

    await session.commit()

    return {
        "removed": len(broken_ids),
        "status": "success",
        "mode": data.mode,
    }
