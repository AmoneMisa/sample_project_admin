from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_session
from ..deps.require_user import require_admin
from ..models.models import User

router = APIRouter(prefix="/users", tags=["users"])

SOFT_DELETE_PERIOD_DAYS = 180


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
async def get_user_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return user


def ensure_not_admin(user: User):
    if user.role == "admin":
        raise HTTPException(400, "Нельзя менять данные администратора")


# ---------------------------------------------------------
# GET /users — список + фильтры
# ---------------------------------------------------------
@router.get("")
async def list_users(
        role: str | None = None,
        email: str | None = None,
        deleted: bool | None = None,
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
    return await get_user_or_404(db, user_id)


# ---------------------------------------------------------
# POST /users/{id}/role — смена роли
# ---------------------------------------------------------
class ChangeRoleRequest(BaseModel):
    role: str  # "observer" или "moderator"


@router.post("/{user_id}/role")
async def change_role(
        user_id: int,
        data: ChangeRoleRequest,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    if data.role not in ("observer", "moderator"):
        raise HTTPException(400, "Недопустимая роль")

    user = await get_user_or_404(db, user_id)
    ensure_not_admin(user)

    user.role = data.role
    await db.commit()
    await db.refresh(user)

    return {"id": user.id, "role": user.role}


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
        raise HTTPException(410, "Профиль окончательно удалён")

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

    return {"id": user.id, "permissions": user.permissions}
