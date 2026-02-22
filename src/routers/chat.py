import json
import re
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Form
from sqlalchemy import select, desc, func

from ..db.session import SessionLocal
from ..services.ws_manager import ws_manager
from ..utils.redis_client import get_redis
from ..models.telegramModels import ChatSession, ChatMessage, SessionStatus

router = APIRouter(prefix="/chat", tags=["chat"])

TG_USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]{5,32}$")

AVAILABLE_LOCALES = [
    {"code": "en", "name": "English"},
    {"code": "ru", "name": "Русский"},
    {"code": "kk", "name": "Қазақша"},
]

def _client_id(request: Request) -> str:
    return (request.headers.get("X-Client-Id") or "").strip()

def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None

async def _get_last_session(db, client_id: str) -> Optional[ChatSession]:
    q = (
        select(ChatSession)
        .where(ChatSession.client_id == client_id)
        .order_by(desc(ChatSession.id))
        .limit(1)
    )
    return (await db.execute(q)).scalars().first()

async def _create_session(db, client_id: str, ip: Optional[str]) -> ChatSession:
    s = ChatSession(client_id=client_id, ip=ip, status=SessionStatus.active)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s

async def _get_or_create_session(db, request: Request, client_id: str, ip: Optional[str]) -> ChatSession:
    s = await _get_last_session(db, client_id)
    if s and s.status != SessionStatus.closed:
        return s

    s = await _create_session(db, client_id, ip)

    r = get_redis()
    await r.publish("tg.notify", json.dumps({
        "type": "session_started",
        "source": "site",
        "sessionId": s.id,
        "clientId": client_id,
        "locale": {"code": "ru", "name": "Русский"},
        "locales": AVAILABLE_LOCALES,
    }, ensure_ascii=False))

    return s

@router.post("/start")
async def start(request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    ip = _ip(request)

    async with SessionLocal() as db:
        s = await _get_or_create_session(db, request, client_id, ip)

        return {
            "ok": True,
            "session": {"id": s.id, "status": s.status, "tgUsername": s.tg_username},
        }

@router.get("/history")
async def history(request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    async with SessionLocal() as db:
        s = await _get_last_session(db, client_id)

        if not s:
            return {"ok": True, "session": None, "messages": []}

        mq = (
            select(ChatMessage)
            .where(ChatMessage.session_id == s.id)
            .order_by(ChatMessage.id.asc())
            .limit(300)
        )
        msgs = (await db.execute(mq)).scalars().all()

        return {
            "ok": True,
            "session": {"id": s.id, "status": s.status, "tgUsername": s.tg_username},
            "messages": [
                {"id": m.id, "sender": m.sender, "text": m.text, "createdAt": m.created_at.isoformat()}
                for m in msgs
            ],
        }

@router.get("/status")
async def status(request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    async with SessionLocal() as db:
        s = await _get_last_session(db, client_id)

        if not s:
            return {"ok": True, "session": None}

        return {"ok": True, "session": {"id": s.id, "status": s.status, "tgUsername": s.tg_username}}

@router.post("/send")
async def send(
        request: Request,
        text: str = Form(""),
):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    text_value = (text or "").strip()
    if not text_value:
        return {"ok": False, "error": "empty"}

    ip = _ip(request)

    async with SessionLocal() as db:
        s = await _get_or_create_session(db, request, client_id, ip)

        if s.status == SessionStatus.moved_to_telegram:
            return {"ok": False, "error": "moved_to_telegram"}

        m = ChatMessage(session_id=s.id, sender="client", text=text_value)
        db.add(m)
        await db.commit()
        await db.refresh(m)

    ws_payload = {
        "type": "message",
        "sessionId": s.id,
        "sender": "client",
        "text": text_value,
        "createdAt": m.created_at.isoformat(),
    }
    await ws_manager.send(client_id, ws_payload)

    try:
        r = get_redis()
        await r.publish("tg.notify", json.dumps({
            "type": "chat_message",
            "source": "site",
            "sessionId": s.id,
            "clientId": client_id,
            "text": text_value,
            "createdAt": m.created_at.isoformat(),
        }, ensure_ascii=False))
    except Exception:
        pass

    return {"ok": True, "sessionId": s.id}

@router.post("/close")
async def close_chat(request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    async with SessionLocal() as db:
        s = await _get_last_session(db, client_id)
        if not s or s.status == SessionStatus.closed:
            return {"ok": True}

        s.status = SessionStatus.closed
        s.closed_at = func.now()
        await db.commit()

    await ws_manager.send(client_id, {
        "type": "session_closed",
        "sessionId": s.id,
        "reason": "closed_by_client",
    })

    try:
        r = get_redis()
        await r.publish("tg.notify", json.dumps({
            "type": "session_closed",
            "source": "site",
            "sessionId": s.id,
            "clientId": client_id,
            "reason": "closed_by_client",
        }, ensure_ascii=False))
    except Exception:
        pass

    return {"ok": True}

@router.post("/set-channel")
async def set_channel(payload: dict, request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    channel = payload.get("channel")
    tg_username = (payload.get("tgUsername") or "").strip()
    ip = _ip(request)

    async with SessionLocal() as db:
        s = await _get_or_create_session(db, request, client_id, ip)

        if channel == "telegram":
            if not TG_USERNAME_RE.match(tg_username):
                return {"ok": False, "error": "invalid_username"}

            s.tg_username = tg_username
            s.status = SessionStatus.moved_to_telegram
            await db.commit()

            r = get_redis()
            await r.publish("tg.notify", json.dumps({
                "type": "moved_to_telegram",
                "source": "telegram",
                "sessionId": s.id,
                "clientId": client_id,
                "tgUsername": tg_username,
            }, ensure_ascii=False))

        elif channel == "site":
            if s.status != SessionStatus.closed:
                s.status = SessionStatus.active
                await db.commit()
        else:
            return {"ok": False, "error": "invalid_channel"}

    return {"ok": True}

@router.websocket("/ws")
async def ws_chat(ws: WebSocket, clientId: str):
    await ws_manager.connect(clientId, ws)
    try:
        while True:
            await ws.receive()
    except WebSocketDisconnect:
        await ws_manager.disconnect(clientId, ws)