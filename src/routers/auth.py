from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from jose import jwt, JWTError
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.deps import oauth2_scheme
from ..auth.jwt import (
    create_access_token,
    create_refresh_token,
    SECRET_KEY,
    ALGORITHM,
)
from ..db.session import get_session
from ..models.models import User


router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------
# Unified API error helper
# ---------------------------------------------------------
def api_error(code: str, message: str, field: Optional[str] = None, status: int = 400):
    detail = {"code": code, "message": message}
    if field:
        detail["field"] = field
    raise HTTPException(status_code=status, detail=detail)


# ---------------------------------------------------------
# Current user
# ---------------------------------------------------------
async def get_current_user(
        token: str = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_session),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("id")
    except JWTError:
        api_error("INVALID_TOKEN", "Неверный токен", status=401)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        api_error("USER_NOT_FOUND", "Пользователь не найден", status=401)

    if user.deleted:
        api_error("ACCOUNT_DELETED", "Аккаунт помечен на удаление", status=403)

    return user


# ---------------------------------------------------------
# /auth/me
# ---------------------------------------------------------
@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "permissions": current_user.permissions,
    }


# ---------------------------------------------------------
# Registration
# ---------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str


@router.post("/register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(User).where(User.email == data.email))
    existing = result.scalar_one_or_none()

    if existing:
        api_error("USER_EXISTS", "Пользователь уже существует", field="email")

    password_hash = bcrypt.hashpw(
        data.password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    user = User(
        email=data.email,
        password_hash=password_hash,
        full_name=data.full_name,
        role="observer",
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    return {"id": user.id, "email": user.email, "role": user.role}


# ---------------------------------------------------------
# Login
# ---------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


@router.post("/login")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        api_error("INVALID_CREDENTIALS", "Неверный email или пароль", field="email", status=401)

    if not bcrypt.checkpw(data.password.encode(), user.password_hash.encode()):
        api_error("INVALID_CREDENTIALS", "Неверный email или пароль", field="password", status=401)

    if user.deleted:
        api_error("ACCOUNT_DELETED", "Профиль помечен на удаление. Восстановите аккаунт.", status=403)

    access_token = create_access_token(
        {"id": user.id, "role": user.role},
        remember=data.remember_me,
    )

    refresh_token, expires = create_refresh_token(user.id)
    user.refresh_token = refresh_token
    user.refresh_token_expires = expires

    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "role": user.role,
        "full_name": user.full_name,
    }


# ---------------------------------------------------------
# Restore account
# ---------------------------------------------------------
class RestoreAccountRequest(BaseModel):
    email: EmailStr
    password: str


SOFT_DELETE_PERIOD_DAYS = 180


@router.post("/restore")
async def restore_account(data: RestoreAccountRequest, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        api_error("USER_NOT_FOUND", "Пользователь не найден", field="email", status=404)

    if not bcrypt.checkpw(data.password.encode(), user.password_hash.encode()):
        api_error("INVALID_PASSWORD", "Неверный пароль", field="password", status=401)

    if not user.deleted:
        token = create_access_token({"id": user.id, "role": user.role})
        return {"status": "active", "token": token}

    if user.deleted_at and datetime.utcnow() - user.deleted_at > timedelta(days=SOFT_DELETE_PERIOD_DAYS):
        api_error("ACCOUNT_GONE", "Профиль окончательно удалён", status=410)

    user.deleted = False
    user.deleted_at = None
    await db.commit()

    token = create_access_token({"id": user.id, "role": user.role})
    return {"status": "restored", "token": token}


# ---------------------------------------------------------
# Refresh token
# ---------------------------------------------------------
class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
async def refresh_token(data: RefreshRequest, db: AsyncSession = Depends(get_session)):
    try:
        payload = jwt.decode(data.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        api_error("INVALID_REFRESH", "Неверный refresh токен", status=401)

    if payload.get("type") != "refresh":
        api_error("INVALID_TOKEN_TYPE", "Неверный тип токена", status=401)

    user_id = payload.get("id")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        api_error("USER_NOT_FOUND", "Пользователь не найден", status=404)

    if user.refresh_token != data.refresh_token:
        api_error("TOKEN_REVOKED", "Refresh токен отозван", status=401)

    if user.refresh_token_expires < datetime.utcnow():
        api_error("TOKEN_EXPIRED", "Refresh токен истёк", status=401)

    new_access = create_access_token({"id": user.id, "role": user.role})
    return {"access_token": new_access}


# ---------------------------------------------------------
# Logout
# ---------------------------------------------------------
@router.post("/logout")
async def logout(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_session),
):
    current_user.refresh_token = None
    current_user.refresh_token_expires = None

    await db.commit()

    return {"status": "logged_out"}
