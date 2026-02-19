import enum
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Enum, ForeignKey, func, Index
)
from sqlalchemy.orm import relationship

from .models import Base

class SessionStatus(str, enum.Enum):
    active = "active"
    awaiting_username = "awaiting_username"
    moved_to_telegram = "moved_to_telegram"
    closed = "closed"

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    client_id = Column(String(64), nullable=False, index=True)
    ip = Column(String(64), nullable=True)
    ua_hash = Column(String(64), nullable=True)

    status = Column(Enum(SessionStatus), nullable=False, server_default="active")
    tg_username = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)

    messages = relationship("ChatMessage", back_populates="session", cascade="all,delete-orphan")

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False, index=True)
    sender = Column(String(16), nullable=False)  # "client" | "owner"
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")

Index("ix_chat_messages_session_id_id", ChatMessage.session_id, ChatMessage.id)
