from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from passlib.hash import bcrypt
from sqlalchemy.orm import Session
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
def get_current_user(
        token: str = Depends(oauth2_scheme),
        db: Session = Depends(get_session),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("id")
    except JWTError:
        raise HTTPException(401, "Неверный токен")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "Пользователь не найден")

    if user.deleted:
        raise HTTPException(403, "Аккаунт помечен на удаление")

    return user


# -----------------------------
#  /auth/me
# -----------------------------
@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "permissions": current_user.permissions,
    }


# -----------------------------
#  Открытая регистрация
# -----------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str


@router.post("/register")
def register(
        data: RegisterRequest,
        db: Session = Depends(get_session),
):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(400, "Пользователь уже существует")

    user = User(
        email=data.email,
        password_hash=bcrypt.hash(data.password),
        full_name=data.full_name,
        role="observer",
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {"id": user.id, "email": user.email, "role": user.role}


# -----------------------------
#  Логин
# -----------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_session)):
    user = db.query(User).filter(User.email == data.email).first()

    if not user or not bcrypt.verify(data.password, user.password_hash):
        raise HTTPException(401, "Неверный email или пароль")

    if user.deleted:
        raise HTTPException(403, "Профиль помечен на удаление. Восстановите аккаунт.")

    # access token
    access_token = create_access_token(
        {"id": user.id, "role": user.role},
        remember=data.remember_me,
    )

    # refresh token
    refresh_token, expires = create_refresh_token(user.id)
    user.refresh_token = refresh_token
    user.refresh_token_expires = expires
    db.commit()

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
def restore_account(data: RestoreAccountRequest, db: Session = Depends(get_session)):
    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if not bcrypt.verify(data.password, user.password_hash):
        raise HTTPException(401, "Неверный пароль")

    # Если не удалён — просто логиним
    if not user.deleted:
        token = create_access_token({"id": user.id, "role": user.role})
        return {"status": "active", "token": token}

    # Проверяем срок soft-delete
    if user.deleted_at and datetime.utcnow() - user.deleted_at > timedelta(days=SOFT_DELETE_PERIOD_DAYS):
        raise HTTPException(410, "Профиль окончательно удалён")

    # Восстанавливаем
    user.deleted = False
    user.deleted_at = None
    db.commit()

    token = create_access_token({"id": user.id, "role": user.role})

    return {"status": "restored", "token": token}


# -----------------------------
#  Refresh token
# -----------------------------
class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
def refresh_token(data: RefreshRequest, db: Session = Depends(get_session)):
    try:
        payload = jwt.decode(data.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Неверный тип токена")
        user_id = payload.get("id")
    except JWTError:
        raise HTTPException(401, "Неверный refresh токен")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.refresh_token != data.refresh_token:
        raise HTTPException(401, "Refresh токен отозван")

    if user.refresh_token_expires < datetime.utcnow():
        raise HTTPException(401, "Refresh токен истёк")

    # выдаём новый access token
    new_access = create_access_token({"id": user.id, "role": user.role})

    return {"access_token": new_access}


# -----------------------------
#  Logout
# -----------------------------
@router.post("/logout")
def logout(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_session),
):
    current_user.refresh_token = None
    current_user.refresh_token_expires = None
    db.commit()
    return {"status": "logged_out"}
