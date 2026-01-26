import bcrypt
from sqlalchemy import select

from .config import settings
from .db.session import SessionLocal
from .models.models import User


async def init_admin():
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.email == settings.ADMIN_LOGIN))
        existing = result.scalar_one_or_none()

        if existing:
            return

        password = settings.ADMIN_PASSWORD.encode("utf-8")
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password, salt).decode("utf-8")

        user = User(
            email=settings.ADMIN_LOGIN,
            password_hash=password_hash,
            full_name="Системный Администратор",
            role="admin",
        )

        db.add(user)
        await db.commit()
