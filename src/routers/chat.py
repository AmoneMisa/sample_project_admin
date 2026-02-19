import json
import re
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import SessionLocal
from ..services.ws_manager import ws_manager
from ..utils.redis_client import get_redis
from ..models.telegramModels import ChatSession, ChatMessage, SessionStatus

router = APIRouter(prefix="/chat", tags=["chat"])

TG_USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]{5,32}$")

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_IMAGE_BYTES = 6 * 1024 * 1024

CHAT_STORAGE_DIR = Path("storage/chat_uploads")


def _client_id(request: Request) -> str:
    return (request.headers.get("X-Client-Id") or "").strip()


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _safe_filename(ext: str) -> str:
    return f"{uuid4().hex}{ext}"


def _ext_from_content_type(content_type: str) -> str:
    if content_type == "image/png":
        return ".png"
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/webp":
        return ".webp"
    return ""


def _build_file_url(request: Request, session_id: int, filename: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/chat/file/{session_id}/{filename}"


async def _get_or_create_session(db: AsyncSession, request: Request, client_id: str, ip: Optional[str]) -> ChatSession:
    q = (
        select(ChatSession)
        .where(ChatSession.client_id == client_id)
        .order_by(desc(ChatSession.id))
        .limit(1)
    )
    s = (await db.execute(q)).scalars().first()
    if s:
        return s

    s = ChatSession(client_id=client_id, ip=ip, status=SessionStatus.active)
    db.add(s)
    await db.commit()
    await db.refresh(s)

    r = get_redis()
    await r.publish("tg.notify", json.dumps({
        "type": "session_started",
        "sessionId": s.id,
        "source": "site",
        "clientId": client_id,
        "locale": {
            "code": getattr(s, "locale_code", "ru") or "ru",
            "name": getattr(s, "locale_name", "Русский") or "Русский",
        },
        "locales": [
            {"code": "en", "name": "English"},
            {"code": "ru", "name": "Русский"},
            {"code": "kk", "name": "Қазақша"},
        ],
    }, ensure_ascii=False))

    return s


async def _save_session_image(session_id: int, file: UploadFile) -> str:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError("invalid_type")

    content = await file.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("too_large")

    ext = _ext_from_content_type(file.content_type)
    if not ext:
        raise ValueError("invalid_type")

    folder = CHAT_STORAGE_DIR / str(session_id)
    folder.mkdir(parents=True, exist_ok=True)

    filename = _safe_filename(ext)
    path = folder / filename
    path.write_bytes(content)

    return filename


@router.get("/history")
async def history(request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    async with SessionLocal() as db:
        q = (
            select(ChatSession)
            .where(ChatSession.client_id == client_id)
            .order_by(desc(ChatSession.id))
            .limit(1)
        )
        s = (await db.execute(q)).scalars().first()

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
            "session": {"id": s.id, "status": s.status, "tgUsername": getattr(s, "tg_username", None)},
            "messages": [
                {
                    "id": m.id,
                    "sender": m.sender,
                    "text": m.text,
                    "createdAt": m.created_at.isoformat(),
                    "imageUrl": getattr(m, "image_url", None)
                }
                for m in msgs
            ],
        }


@router.get("/status")
async def status(request: Request):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    async with SessionLocal() as db:
        q = (
            select(ChatSession)
            .where(ChatSession.client_id == client_id)
            .order_by(desc(ChatSession.id))
            .limit(1)
        )
        s = (await db.execute(q)).scalars().first()

        if not s:
            return {"ok": True, "session": None}

        return {"ok": True, "session": {"id": s.id, "status": s.status, "tgUsername": getattr(s, "tg_username", None)}}


@router.post("/send")
async def send(
        request: Request,
        text: str = Form(""),
        file: UploadFile | None = File(default=None),
):
    client_id = _client_id(request)
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}

    text_value = (text or "").strip()
    if not text_value and file is None:
        return {"ok": False, "error": "empty"}

    ip = _ip(request)

    image_url: Optional[str] = None

    async with SessionLocal() as db:
        s = await _get_or_create_session(db, request, client_id, ip)
        if s.status == SessionStatus.closed:
            return {"ok": False, "error": "closed"}

        if file is not None:
            try:
                filename = await _save_session_image(s.id, file)
            except ValueError as e:
                code = str(e)
                if code == "invalid_type":
                    return {"ok": False, "error": "invalid_file_type"}
                if code == "too_large":
                    return {"ok": False, "error": "file_too_large"}
                return {"ok": False, "error": "file_error"}

            image_url = _build_file_url(request, s.id, filename)

        m = ChatMessage(session_id=s.id, sender="client", text=text_value)
        if hasattr(m, "image_url"):
            setattr(m, "image_url", image_url)
        db.add(m)

        if hasattr(s, "last_activity_at"):
            setattr(s, "last_activity_at", func.now())

        await db.commit()
        await db.refresh(m)

    ws_payload = {
        "type": "message",
        "sessionId": s.id,
        "sender": "client",
        "text": text_value,
        "createdAt": m.created_at.isoformat(),
        "imageUrl": image_url,
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
            "imageUrl": image_url,
        }, ensure_ascii=False))
    except Exception:
        pass

    return {"ok": True, "sessionId": s.id}


@router.post("/owner-reply")
async def owner_reply(
        request: Request,
        sessionId: int = Form(...),
        text: str = Form(""),
        file: UploadFile | None = File(default=None),
):
    text_value = (text or "").strip()
    if not text_value and file is None:
        return {"ok": False, "error": "empty"}

    image_url: Optional[str] = None
    client_id: Optional[str] = None

    async with SessionLocal() as db:
        s = await db.get(ChatSession, int(sessionId))
        if not s or s.status == SessionStatus.closed:
            return {"ok": False, "error": "closed"}

        client_id = s.client_id

        if file is not None:
            try:
                filename = await _save_session_image(s.id, file)
            except ValueError as e:
                code = str(e)
                if code == "invalid_type":
                    return {"ok": False, "error": "invalid_file_type"}
                if code == "too_large":
                    return {"ok": False, "error": "file_too_large"}
                return {"ok": False, "error": "file_error"}

            image_url = _build_file_url(request, s.id, filename)

        m = ChatMessage(session_id=s.id, sender="owner", text=text_value)
        if hasattr(m, "image_url"):
            setattr(m, "image_url", image_url)
        db.add(m)

        if hasattr(s, "last_activity_at"):
            setattr(s, "last_activity_at", func.now())

        await db.commit()
        await db.refresh(m)

    await ws_manager.send(client_id, {
        "type": "message",
        "sessionId": int(sessionId),
        "sender": "owner",
        "text": text_value,
        "createdAt": m.created_at.isoformat(),
        "imageUrl": image_url,
    })

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
        if s.status == SessionStatus.closed:
            return {"ok": False, "error": "closed"}

        if channel == "telegram":
            if not TG_USERNAME_RE.match(tg_username):
                return {"ok": False, "error": "invalid_username"}

            if hasattr(s, "tg_username"):
                setattr(s, "tg_username", tg_username)

            if hasattr(s, "status"):
                s.status = SessionStatus.awaiting_username

            if hasattr(s, "last_activity_at"):
                setattr(s, "last_activity_at", func.now())

            await db.commit()

            r = get_redis()
            await r.publish("tg.notify", json.dumps({
                "type": "request_tg_username",
                "source": "telegram",
                "sessionId": s.id,
                "clientId": client_id,
                "tgUsername": tg_username,
            }, ensure_ascii=False))

        elif channel == "site":
            if s.status != SessionStatus.closed:
                s.status = SessionStatus.active
                if hasattr(s, "last_activity_at"):
                    setattr(s, "last_activity_at", func.now())
                await db.commit()

        else:
            return {"ok": False, "error": "invalid_channel"}

    return {"ok": True}


@router.get("/file/{sessionId}/{filename}")
async def get_file(sessionId: int, filename: str):
    path = CHAT_STORAGE_DIR / str(int(sessionId)) / filename
    if not path.exists():
        return {"ok": False, "error": "not_found"}
    return FileResponse(path)


@router.websocket("/ws")
async def ws_chat(ws: WebSocket, clientId: str):
    await ws_manager.connect(clientId, ws)
    try:
        while True:
            await ws.receive()
    except WebSocketDisconnect:
        await ws_manager.disconnect(clientId, ws)
