from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db.session import get_session
from ..deps.require_user import require_admin
from ..models.models import User

router = APIRouter(prefix="/users", tags=["users"])


# -----------------------------
#  Список пользователей (только админ)
# -----------------------------
@router.get("/")
async def list_users(
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    result = await db.execute(select(User))
    return result.scalars().all()


@router.get("/by-role/{role}")
async def list_users_by_role(
        role: str,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.role == role))
    return result.scalars().all()


@router.get("/by-id/{user_id}")
async def get_user_by_id(
        user_id: int,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "Пользователь не найден")

    return user


@router.get("/by-email")
async def get_user_by_email(
        email: str = Query(...),
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "Пользователь не найден")

    return user


# -----------------------------
#  Смена роли (только админ)
# -----------------------------
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

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.role == "admin":
        raise HTTPException(400, "Нельзя менять роль администратора")

    user.role = data.role
    await db.commit()
    await db.refresh(user)

    return {"id": user.id, "role": user.role}


# -----------------------------
#  Soft delete (только админ)
# -----------------------------
SOFT_DELETE_PERIOD_DAYS = 180


@router.post("/{user_id}/delete")
async def soft_delete_user(
        user_id: int,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.role == "admin":
        raise HTTPException(400, "Нельзя удалить администратора")

    user.deleted = True
    user.deleted_at = datetime.utcnow()

    await db.commit()
    return {"status": "marked_deleted"}


# -----------------------------
#  Restore (только админ)
# -----------------------------
@router.post("/{user_id}/restore")
async def restore_user(
        user_id: int,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if not user.deleted:
        return {"status": "not_deleted"}

    if user.deleted_at and datetime.utcnow() - user.deleted_at > timedelta(days=SOFT_DELETE_PERIOD_DAYS):
        raise HTTPException(410, "Профиль окончательно удалён")

    user.deleted = False
    user.deleted_at = None

    await db.commit()
    return {"status": "restored"}


# -----------------------------
#  Обновление прав (только админ)
# -----------------------------
class PermissionsUpdateRequest(BaseModel):
    permissions: dict


@router.post("/{user_id}/permissions")
async def update_permissions(
        user_id: int,
        data: PermissionsUpdateRequest,
        db: AsyncSession = Depends(get_session),
        admin: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.role == "admin":
        raise HTTPException(400, "Нельзя менять права администратора")

    user.permissions = data.permissions

    await db.commit()
    await db.refresh(user)

    return {"id": user.id, "permissions": user.permissions}
