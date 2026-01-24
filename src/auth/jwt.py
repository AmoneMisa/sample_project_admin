from datetime import datetime, timedelta
from jose import jwt
from ..config import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES = 60
ACCESS_TOKEN_EXPIRE_REMEMBER_MINUTES = 60 * 24 * 30  # 30 дней
REFRESH_TOKEN_EXPIRE_DAYS = 30


def create_access_token(data: dict, remember: bool = False):
    expire_minutes = (
        ACCESS_TOKEN_EXPIRE_REMEMBER_MINUTES if remember else ACCESS_TOKEN_EXPIRE_MINUTES
    )
    expire = datetime.utcnow() + timedelta(minutes=expire_minutes)
    to_encode = {**data, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: int):
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {"id": user_id, "exp": expire, "type": "refresh"}
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return token, expire
