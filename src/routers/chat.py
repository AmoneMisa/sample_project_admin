import json
import re
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import SessionLocal
from ..services.ws_manager import ws_manager
from ..utils.redis_client import get_redis
from ..models.telegramModels import ChatSession, ChatMessage, SessionStatus

router = APIRouter(prefix="/chat", tags=["chat"])

TG_USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]{5,32}$")


def _client_id(request: Request) -> str:
    return (request.headers.get("X-Client-Id") or "").strip()


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


async def _push_ws_message(client_id: str, session_id: int, sender: str, text: str, created_at_iso: str):
    await ws_manager.send(client_id, {
        "type": "message",
        "sessionId": session_id,
        "sender": sender,
        "text": text,
        "createdAt": created_at_iso,
    })


async def _add_message(db: AsyncSession, session_id: int, sender: str, text: str) -> ChatMessage:
    m = ChatMessage(session_id=session_id, sender=sender, text=text)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def _get_last_session(db: AsyncSession, client_id: str) -> Optional[ChatSession]:
    q = (
        select(ChatSession)
        .where(ChatSession.client_id == client_id)
        .order_by(desc(ChatSession.id))
        .limit(1)
    )
    return (await db.execute(q)).scalars().first()


async def _get_or_create_session(db: AsyncSession, client_id: str, ip: Optional[str]) -> ChatSession:
    s = await _get_last_session(db, client_id)
    if s:
        return s

    s = ChatSession(client_id=client_id, ip=ip, status=SessionStatus.new)
    db.add(s)
    await db.commit()
    await db.refresh(s)

    if hasattr(s, "last_activity_at"):
        setattr(s, "last_activity_at", func.now())
        await db.commit()

    intro = "Где вам удобнее продолжить общение: на сайте или в Telegram?"
    m = await _add_message(db, s.id, "owner", intro)

    await _push_ws_message(client_id, s.id, "owner", intro, m.created_at.isoformat())

    try:
        r = get_redis()
        await r.publish("tg.notify", json.dumps({
            "type": "session_started",
            "source": "site",
            "sessionId": s.id,
            "clientId": client_id,
        }, ensure_ascii=False))
    except Exception:
        pass

    return s


@router.get("/history")
async def history(request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    ip = _ip(request)

    async with SessionLocal() as db:
        s = await _get_or_create_session(db, client_id, ip)

        mq = (
            select(ChatMessage)
            .where(ChatMessage.session_id == s.id)
            .order_by(ChatMessage.id.asc())
            .limit(300)
        )
        msgs = (await db.execute(mq)).scalars().all()

        return {
            "ok": True,
            "session": {
                "id": s.id,
                "status": s.status,
                "tgUsername": getattr(s, "tg_username", None),
            },
            "messages": [
                {
                    "id": m.id,
                    "sender": m.sender,
                    "text": m.text,
                    "createdAt": m.created_at.isoformat(),
                }
                for m in msgs
            ],
        }


@router.post("/choose")
async def choose(payload: dict, request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    channel = (payload.get("channel") or "").strip()
    if channel not in ("site", "telegram"):
        return {"ok": False, "error": "invalid_channel"}

    ip = _ip(request)

    async with SessionLocal() as db:
        s = await _get_or_create_session(db, client_id, ip)
        if s.status == SessionStatus.closed:
            return {"ok": False, "error": "closed"}

        if channel == "site":
            s.status = SessionStatus.active
            if hasattr(s, "last_activity_at"):
                setattr(s, "last_activity_at", func.now())
            await db.commit()

            text = "Ок. Напишите сообщение здесь — и я отвечу."
            m = await _add_message(db, s.id, "owner", text)
            await _push_ws_message(client_id, s.id, "owner", text, m.created_at.isoformat())
            return {"ok": True}

        s.status = SessionStatus.awaiting_username
        if hasattr(s, "last_activity_at"):
            setattr(s, "last_activity_at", func.now())
        await db.commit()

        text = "Введите ваш ник в Telegram в формате @username"
        m = await _add_message(db, s.id, "owner", text)
        await _push_ws_message(client_id, s.id, "owner", text, m.created_at.isoformat())

        return {"ok": True}


@router.post("/set-telegram")
async def set_telegram(payload: dict, request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    tg_username = (payload.get("tgUsername") or "").strip()
    if not TG_USERNAME_RE.match(tg_username):
        return {"ok": False, "error": "invalid_username"}

    ip = _ip(request)

    async with SessionLocal() as db:
        s = await _get_or_create_session(db, client_id, ip)
        if s.status == SessionStatus.closed:
            return {"ok": False, "error": "closed"}

        if hasattr(s, "tg_username"):
            setattr(s, "tg_username", tg_username)

        s.status = SessionStatus.closed
        if hasattr(s, "closed_at"):
            setattr(s, "closed_at", func.now())
        if hasattr(s, "last_activity_at"):
            setattr(s, "last_activity_at", func.now())

        await db.commit()

        thanks = "Спасибо. Разработчик свяжется с вами как можно скорее с ника @WhitesLove"
        m = await _add_message(db, s.id, "owner", thanks)
        await _push_ws_message(client_id, s.id, "owner", thanks, m.created_at.isoformat())

        await ws_manager.send(client_id, {
            "type": "session_closed",
            "sessionId": s.id,
            "reason": "telegram",
        })

        try:
            r = get_redis()
            await r.publish("tg.notify", json.dumps({
                "type": "tg_username",
                "source": "site",
                "sessionId": s.id,
                "clientId": client_id,
                "tgUsername": tg_username,
            }, ensure_ascii=False))
        except Exception:
            pass

        return {"ok": True}


@router.post("/send")
async def send(payload: dict, request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    text = (payload.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "empty"}

    ip = _ip(request)

    async with SessionLocal() as db:
        s = await _get_or_create_session(db, client_id, ip)
        if s.status != SessionStatus.active:
            return {"ok": False, "error": "not_active"}

        m = await _add_message(db, s.id, "client", text)

        if hasattr(s, "last_activity_at"):
            setattr(s, "last_activity_at", func.now())
            await db.commit()

    await _push_ws_message(client_id, s.id, "client", text, m.created_at.isoformat())

    try:
        r = get_redis()
        await r.publish("tg.notify", json.dumps({
            "type": "chat_message",
            "source": "site",
            "sessionId": s.id,
            "clientId": client_id,
            "text": text,
            "createdAt": m.created_at.isoformat(),
        }, ensure_ascii=False))
    except Exception:
        pass

    return {"ok": True, "sessionId": s.id}


@router.websocket("/ws")
async def ws_chat(ws: WebSocket, clientId: str):
    await ws_manager.connect(clientId, ws)
    try:
        while True:
            await ws.receive()
    except WebSocketDisconnect:
        await ws_manager.disconnect(clientId, ws)