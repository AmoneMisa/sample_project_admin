from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_admin
from ..models.models import User

router = APIRouter(prefix="/users", tags=["users"])

SOFT_DELETE_PERIOD_DAYS = 180


# ---------------------------------------------------------
# Unified API error helper
# ---------------------------------------------------------
def api_error(code: str, message: str, status: int = 400, field: Optional[str] = None):
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    raise HTTPException(status_code=status, detail=detail)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
async def get_user_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        api_error("USER_NOT_FOUND", "Пользователь не найден", status=404)
    return user


def ensure_not_admin(user: User):
    if user.role == "admin":
        api_error("FORBIDDEN", "Нельзя менять данные администратора", status=400)


# ---------------------------------------------------------
# GET /users — список + фильтры
# ---------------------------------------------------------
@router.get("")
async def list_users(
        role: Optional[str] = None,
        email: Optional[str] = None,
        deleted: Optional[bool] = None,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    query = select(User)

    if role is not None:
        query = query.where(User.role == role)

    if email is not None:
        query = query.where(User.email == email)

    if deleted is not None:
        query = query.where(User.deleted == deleted)

    result = await db.execute(query)
    return result.scalars().all()


# ---------------------------------------------------------
# GET /users/{id}
# ---------------------------------------------------------
@router.get("/{user_id}")
async def get_user_by_id(
        user_id: int,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    user = await get_user_or_404(db, user_id)
    return user


# ---------------------------------------------------------
# POST /users/{id}/role — смена роли
# ---------------------------------------------------------
class ChangeRoleRequest(BaseModel):
    role: str = Field(..., min_length=1)


@router.post("/{user_id}/role")
async def change_role(
        user_id: int,
        data: ChangeRoleRequest,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    if data.role not in ("observer", "moderator"):
        api_error("INVALID_ROLE", "Недопустимая роль", field="role", status=422)

    user = await get_user_or_404(db, user_id)
    ensure_not_admin(user)

    user.role = data.role
    await db.commit()
    await db.refresh(user)

    return {"status": "updated", "id": user.id, "role": user.role}


# ---------------------------------------------------------
# POST /users/{id}/delete — soft delete
# ---------------------------------------------------------
@router.post("/{user_id}/delete")
async def soft_delete_user(
        user_id: int,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    user = await get_user_or_404(db, user_id)
    ensure_not_admin(user)

    user.deleted = True
    user.deleted_at = datetime.utcnow()

    await db.commit()
    return {"status": "marked_deleted"}


# ---------------------------------------------------------
# POST /users/{id}/restore — восстановление
# ---------------------------------------------------------
@router.post("/{user_id}/restore")
async def restore_user(
        user_id: int,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    user = await get_user_or_404(db, user_id)

    if not user.deleted:
        return {"status": "not_deleted"}

    if user.deleted_at and datetime.utcnow() - user.deleted_at > timedelta(days=SOFT_DELETE_PERIOD_DAYS):
        api_error("GONE", "Профиль окончательно удалён", status=410)

    user.deleted = False
    user.deleted_at = None

    await db.commit()
    return {"status": "restored"}


# ---------------------------------------------------------
# POST /users/{id}/permissions — обновление прав
# ---------------------------------------------------------
class PermissionsUpdateRequest(BaseModel):
    permissions: dict


@router.post("/{user_id}/permissions")
async def update_permissions(
        user_id: int,
        data: PermissionsUpdateRequest,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    user = await get_user_or_404(db, user_id)
    ensure_not_admin(user)

    user.permissions = data.permissions

    await db.commit()
    await db.refresh(user)

    return {"status": "updated", "id": user.id, "permissions": user.permissions}
