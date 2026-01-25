import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from jose import jwt, JWTError

from ..db.session import get_session
from ..models.models import User
from ..auth.deps import oauth2_scheme
from ..auth.jwt import (
    create_access_token,
    create_refresh_token,
    SECRET_KEY,
    ALGORITHM,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# -----------------------------
#  Получение текущего пользователя
# -----------------------------
async def get_current_user(
        token: str = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_session),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("id")
    except JWTError:
        raise HTTPException(401, "Неверный токен")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(401, "Пользователь не найден")

    if user.deleted:
        raise HTTPException(403, "Аккаунт помечен на удаление")

    return user


# -----------------------------
#  /auth/me
# -----------------------------
@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "permissions": current_user.permissions,
    }


# -----------------------------
#  Регистрация
# -----------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str


@router.post("/register")
async def register(
        data: RegisterRequest,
        db: AsyncSession = Depends(get_session),
):
    result = await db.execute(select(User).where(User.email == data.email))
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(400, "Пользователь уже существует")

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


# -----------------------------
#  Логин
# -----------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


@router.post("/login")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(401, "Неверный email или пароль")

    if not bcrypt.checkpw(
            data.password.encode("utf-8"),
            user.password_hash.encode("utf-8")
    ):
        raise HTTPException(401, "Неверный email или пароль")

    if user.deleted:
        raise HTTPException(403, "Профиль помечен на удаление. Восстановите аккаунт.")

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


# -----------------------------
#  Восстановление аккаунта
# -----------------------------
class RestoreAccountRequest(BaseModel):
    email: EmailStr
    password: str


SOFT_DELETE_PERIOD_DAYS = 180


@router.post("/restore")
async def restore_account(
        data: RestoreAccountRequest,
        db: AsyncSession = Depends(get_session),
):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if not bcrypt.checkpw(
            data.password.encode("utf-8"),
            user.password_hash.encode("utf-8")
    ):
        raise HTTPException(401, "Неверный пароль")

    if not user.deleted:
        token = create_access_token({"id": user.id, "role": user.role})
        return {"status": "active", "token": token}

    if user.deleted_at and datetime.utcnow() - user.deleted_at > timedelta(days=SOFT_DELETE_PERIOD_DAYS):
        raise HTTPException(410, "Профиль окончательно удалён")

    user.deleted = False
    user.deleted_at = None

    await db.commit()

    token = create_access_token({"id": user.id, "role": user.role})
    return {"status": "restored", "token": token}


# -----------------------------
#  Refresh token
# -----------------------------
class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
async def refresh_token(data: RefreshRequest, db: AsyncSession = Depends(get_session)):
    try:
        payload = jwt.decode(data.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Неверный тип токена")
        user_id = payload.get("id")
    except JWTError:
        raise HTTPException(401, "Неверный refresh токен")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.refresh_token != data.refresh_token:
        raise HTTPException(401, "Refresh токен отозван")

    if user.refresh_token_expires < datetime.utcnow():
        raise HTTPException(401, "Refresh токен истёк")

    new_access = create_access_token({"id": user.id, "role": user.role})

    return {"access_token": new_access}


# -----------------------------
#  Logout
# -----------------------------
@router.post("/logout")
async def logout(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_session),
):
    current_user.refresh_token = None
    current_user.refresh_token_expires = None

    await db.commit()

    return {"status": "logged_out"}
