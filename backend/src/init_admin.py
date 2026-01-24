from sqlalchemy.orm import Session
from passlib.hash import bcrypt
from .models.models import User
from .db.session import get_session
from .config import settings

def init_admin():
    db: Session = next(get_session())

    existing = db.query(User).filter(User.email == settings.ADMIN_LOGIN).first()
    if existing:
        return

    user = User(
        email=settings.ADMIN_LOGIN,
        password_hash=bcrypt.hash(settings.ADMIN_PASSWORD),
        full_name="Системный Администратор",
        role="admin"
    )

    db.add(user)
    db.commit()
