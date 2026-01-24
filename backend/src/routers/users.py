from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db.session import get_session
from ..deps.require_user import require_admin
from ..models.models import User

router = APIRouter(prefix="/users", tags=["users"])


# -----------------------------
#  Список пользователей (только админ)
# -----------------------------
@router.get("/")
def list_users(
        db: Session = Depends(get_session),
        admin: User = Depends(require_admin),
):
    return db.query(User).all()


@router.get("/by-role/{role}")
def list_users_by_role(
        role: str,
        db: Session = Depends(get_session),
        admin: User = Depends(require_admin),
):
    return db.query(User).filter(User.role == role).all()


@router.get("/by-id/{user_id}")
def get_user_by_id(
        user_id: int,
        db: Session = Depends(get_session),
        admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return user


@router.get("/by-email")
def get_user_by_email(
        email: str = Query(...),
        db: Session = Depends(get_session),
        admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return user


# -----------------------------
#  Смена роли (только админ)
# -----------------------------
class ChangeRoleRequest(BaseModel):
    role: str  # "observer" или "moderator"


@router.post("/{user_id}/role")
def change_role(
        user_id: int,
        data: ChangeRoleRequest,
        db: Session = Depends(get_session),
        admin: User = Depends(require_admin),
):
    if data.role not in ("observer", "moderator"):
        raise HTTPException(400, "Недопустимая роль")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.role == "admin":
        raise HTTPException(400, "Нельзя менять роль администратора")

    user.role = data.role
    db.commit()
    db.refresh(user)
    return {"id": user.id, "role": user.role}


# -----------------------------
#  Soft delete (только админ)
# -----------------------------
SOFT_DELETE_PERIOD_DAYS = 180


@router.post("/{user_id}/delete")
def soft_delete_user(
        user_id: int,
        db: Session = Depends(get_session),
        admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.role == "admin":
        raise HTTPException(400, "Нельзя удалить администратора")

    user.deleted = True
    user.deleted_at = datetime.utcnow()
    db.commit()
    return {"status": "marked_deleted"}


# -----------------------------
#  Restore (только админ)
# -----------------------------
@router.post("/{user_id}/restore")
def restore_user(
        user_id: int,
        db: Session = Depends(get_session),
        admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if not user.deleted:
        return {"status": "not_deleted"}

    if user.deleted_at and datetime.utcnow() - user.deleted_at > timedelta(days=SOFT_DELETE_PERIOD_DAYS):
        raise HTTPException(410, "Профиль окончательно удалён")

    user.deleted = False
    user.deleted_at = None
    db.commit()
    return {"status": "restored"}


# -----------------------------
#  Обновление прав (только админ)
# -----------------------------
class PermissionsUpdateRequest(BaseModel):
    permissions: dict


@router.post("/{user_id}/permissions")
def update_permissions(
        user_id: int,
        data: PermissionsUpdateRequest,
        db: Session = Depends(get_session),
        admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.role == "admin":
        raise HTTPException(400, "Нельзя менять права администратора")

    user.permissions = data.permissions
    db.commit()
    db.refresh(user)
    return {"id": user.id, "permissions": user.permissions}
