import json
import re
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select, desc, func, exists, and_

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


async def _get_last_session(db, client_id: str) -> Optional[ChatSession]:
    q = (
        select(ChatSession)
        .where(ChatSession.client_id == client_id)
        .order_by(desc(ChatSession.id))
        .limit(1)
    )
    return (await db.execute(q)).scalars().first()


async def _has_client_messages(db, session_id: int) -> bool:
    q = select(
        exists().where(
            and_(
                ChatMessage.session_id == session_id,
                ChatMessage.sender == "client",
                )
        )
    )
    return bool((await db.execute(q)).scalar())


async def _compute_stage(db, s: ChatSession) -> str:
    if s.status == SessionStatus.closed:
        return "closed"
    if s.status == SessionStatus.moved_to_telegram:
        return "closed"
    if s.status == SessionStatus.awaiting_username:
        return "awaiting_username"
    if s.status == SessionStatus.active:
        has_client = await _has_client_messages(db, s.id)
        if (not has_client) and (s.tg_username is None):
            return "choose"
        return "active"
    return "choose"


async def _push_session_update(client_id: str, s: ChatSession, stage: str):
    await ws_manager.send(client_id, {
        "type": "session_update",
        "sessionId": s.id,
        "status": s.status,
        "stage": stage,
        "tgUsername": s.tg_username,
    })


async def _push_message(client_id: str, m: ChatMessage):
    await ws_manager.send(client_id, {
        "type": "message",
        "sessionId": m.session_id,
        "id": m.id,
        "sender": m.sender,
        "text": m.text,
        "createdAt": m.created_at.isoformat(),
    })


async def _push_closed(client_id: str, session_id: int, reason: str):
    await ws_manager.send(client_id, {
        "type": "session_closed",
        "sessionId": session_id,
        "reason": reason,
    })


async def _add_message(db, session_id: int, sender: str, text: str) -> ChatMessage:
    m = ChatMessage(session_id=session_id, sender=sender, text=text)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def _get_or_create_session(db, client_id: str, ip: Optional[str]) -> ChatSession:
    s = await _get_last_session(db, client_id)
    if s:
        return s

    s = ChatSession(client_id=client_id, ip=ip, status=SessionStatus.active)
    db.add(s)
    await db.commit()
    await db.refresh(s)

    intro = "Где вам удобнее продолжить общение: на сайте или в Telegram?"
    m = await _add_message(db, s.id, "owner", intro)
    await _push_message(client_id, m)

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
        stage = await _compute_stage(db, s)

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
                "stage": stage,
                "tgUsername": s.tg_username,
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
        if s.status in (SessionStatus.closed, SessionStatus.moved_to_telegram):
            return {"ok": False, "error": "closed"}

        if channel == "site":
            s.status = SessionStatus.active
            await db.commit()

            text = "Ок. Напишите сообщение здесь — и я отвечу."
            m = await _add_message(db, s.id, "owner", text)
            await _push_message(client_id, m)

            stage = await _compute_stage(db, s)
            await _push_session_update(client_id, s, stage)
            return {"ok": True}

        s.status = SessionStatus.awaiting_username
        await db.commit()

        text = "Введите ваш ник в Telegram в формате @username"
        m = await _add_message(db, s.id, "owner", text)
        await _push_message(client_id, m)

        stage = await _compute_stage(db, s)
        await _push_session_update(client_id, s, stage)
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
        if s.status in (SessionStatus.closed, SessionStatus.moved_to_telegram):
            return {"ok": False, "error": "closed"}

        s.tg_username = tg_username
        s.status = SessionStatus.moved_to_telegram
        s.closed_at = func.now()
        await db.commit()

        thanks = "Спасибо. Разработчик свяжется с вами как можно скорее с ника @WhitesLove"
        m = await _add_message(db, s.id, "owner", thanks)
        await _push_message(client_id, m)

        stage = await _compute_stage(db, s)
        await _push_session_update(client_id, s, stage)
        await _push_closed(client_id, s.id, "telegram")

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
        stage = await _compute_stage(db, s)

        if stage != "active":
            return {"ok": False, "error": "not_active"}

        m = await _add_message(db, s.id, "client", text)
        await _push_message(client_id, m)

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


@router.post("/owner-reply")
async def owner_reply(payload: dict, request: Request):
    session_id = int(payload.get("sessionId") or 0)
    text = (payload.get("text") or "").strip()

    if not session_id or not text:
        return {"ok": False, "error": "empty"}

    async with SessionLocal() as db:
        s = await db.get(ChatSession, session_id)
        if not s:
            return {"ok": False, "error": "not_found"}
        if s.status in (SessionStatus.closed,):
            return {"ok": False, "error": "closed"}

        client_id = s.client_id

        m = await _add_message(db, s.id, "owner", text)
        await _push_message(client_id, m)

        stage = await _compute_stage(db, s)
        await _push_session_update(client_id, s, stage)

        return {"ok": True}


@router.post("/close")
async def close(payload: dict, request: Request):
    session_id = int(payload.get("sessionId") or 0)
    reason = (payload.get("reason") or "closed").strip()
    if not session_id:
        return {"ok": False, "error": "empty"}

    async with SessionLocal() as db:
        s = await db.get(ChatSession, session_id)
        if not s:
            return {"ok": False, "error": "not_found"}

        if s.status != SessionStatus.closed:
            s.status = SessionStatus.closed
            s.closed_at = func.now()
            await db.commit()

        client_id = s.client_id
        stage = await _compute_stage(db, s)
        await _push_session_update(client_id, s, stage)
        await _push_closed(client_id, s.id, reason)

        return {"ok": True}


@router.websocket("/ws")
async def ws_chat(ws: WebSocket, clientId: str):
    await ws_manager.connect(clientId, ws)
    try:
        while True:
            await ws.receive()
    except WebSocketDisconnect:
        await ws_manager.disconnect(clientId, ws)