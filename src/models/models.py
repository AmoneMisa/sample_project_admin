from sqlalchemy import (
    Column, Integer, String, Enum, Boolean, DateTime, ForeignKey, UniqueConstraint, JSON
)
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base import Base

# -------------------------
# User
# -------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(
        Enum("admin", "moderator", "observer", name="user_roles"),
        default="observer",
        nullable=False,
    )

    deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    permissions = Column(JSON, nullable=True, default=dict)
    refresh_token = Column(String(512), nullable=True)
    refresh_token_expires = Column(DateTime, nullable=True)
    translation_versions = relationship(
        "TranslationVersion",
        back_populates="createdBy"
    )

# -------------------------
# Language
# -------------------------
class Language(Base):
    __tablename__ = "Language"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    isEnabled = Column(Boolean, default=True)
    createdAt = Column(DateTime, default=datetime.utcnow)
    updatedAt = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    values = relationship("TranslationValue", back_populates="language")
    versions = relationship("TranslationVersion", back_populates="language")


# -------------------------
# TranslationKey
# -------------------------
class TranslationKey(Base):
    __tablename__ = "TranslationKey"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(255), unique=True, nullable=False)
    namespace = Column(String(255), nullable=True)
    createdAt = Column(DateTime, default=datetime.utcnow)
    updatedAt = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    values = relationship("TranslationValue", back_populates="key")
    versions = relationship("TranslationVersion", back_populates="key")


# -------------------------
# TranslationValue
# -------------------------
class TranslationValue(Base):
    __tablename__ = "TranslationValue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    languageId = Column(Integer, ForeignKey("Language.id"), nullable=False)
    translationKeyId = Column(Integer, ForeignKey("TranslationKey.id"), nullable=False)
    value = Column(JSON, nullable=False)

    language = relationship("Language", back_populates="values")
    key = relationship("TranslationKey", back_populates="values")

    __table_args__ = (
        UniqueConstraint("languageId", "translationKeyId"),
    )


# -------------------------
# TranslationVersion
# -------------------------
class TranslationVersion(Base):
    __tablename__ = "TranslationVersion"

    id = Column(Integer, primary_key=True, autoincrement=True)
    translationKeyId = Column(Integer, ForeignKey("TranslationKey.id"), nullable=False)
    languageId = Column(Integer, ForeignKey("Language.id"), nullable=False)
    value = Column(String(5000), nullable=False)
    createdAt = Column(DateTime, default=datetime.utcnow)
    createdById = Column(Integer, ForeignKey("users.id"), nullable=True)

    key = relationship("TranslationKey", back_populates="versions")
    language = relationship("Language", back_populates="versions")
    createdBy = relationship("User", back_populates="translation_versions")


# -------------------------
# Block
# -------------------------
class Block(Base):
    __tablename__ = "Block"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False)
    order = Column(Integer, nullable=False)
    isVisible = Column(Boolean, default=True)
    config = Column(JSON, nullable=True)


# -------------------------
# ChangeHistory
# -------------------------
class ChangeHistory(Base):
    __tablename__ = "ChangeHistory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    userId = Column(Integer, nullable=True)
    payload = Column(JSON, nullable=False)
    createdAt = Column(DateTime, default=datetime.utcnow)


# -------------------------
# Testimonial
# -------------------------
class Testimonial(Base):
    __tablename__ = "Testimonial"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    role = Column(String(255), nullable=False)
    quote = Column(String(2000), nullable=False)
    avatar = Column(String(500), nullable=True)
    logo = Column(String(500), nullable=True)
    rating = Column(Integer, nullable=False)
    order = Column(Integer, default=0)
    isVisible = Column(Boolean, default=True)


# -------------------------
# PriceCard
# -------------------------
class PriceCard(Base):
    __tablename__ = "PriceCard"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    subtitle = Column(String(255), nullable=True)
    price = Column(String(255), nullable=False)
    features = Column(JSON, nullable=False)
    order = Column(Integer, default=0)
    isVisible = Column(Boolean, default=True)


# -------------------------
# HeaderMenu
# -------------------------
class HeaderMenu(Base):
    __tablename__ = "HeaderMenu"

    id = Column(Integer, primary_key=True, autoincrement=True)
    json = Column(JSON, nullable=False)
    updatedAt = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# -------------------------
# FooterMenuGroup
# -------------------------
class FooterMenuGroup(Base):
    __tablename__ = "FooterMenuGroup"

    id = Column(Integer, primary_key=True, autoincrement=True)
    titleKey = Column(String(255), nullable=False)
    order = Column(Integer, nullable=False)

    items = relationship("FooterMenuItem", back_populates="group")


# -------------------------
# FooterMenuItem
# -------------------------
class FooterMenuItem(Base):
    __tablename__ = "FooterMenuItem"

    id = Column(Integer, primary_key=True, autoincrement=True)
    groupId = Column(Integer, ForeignKey("FooterMenuGroup.id"), nullable=False)
    labelKey = Column(String(255), nullable=False)
    href = Column(String(500), nullable=False)
    order = Column(Integer, nullable=False)
    isVisible = Column(Boolean, default=True)

    group = relationship("FooterMenuGroup", back_populates="items")


# -------------------------
# Contact
# -------------------------
class Contact(Base):
    __tablename__ = "Contact"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False)
    label = Column(String(255), nullable=True)
    value = Column(String(500), nullable=False)
    order = Column(Integer, default=0)
    isVisible = Column(Boolean, default=True)
