import json

from sqlalchemy import func

from ..db.session import SessionLocal
from ..utils.redis_client import get_redis
from ..models.telegramModels import ChatSession, ChatMessage, SessionStatus
from .ws_manager import ws_manager

OWNER_REPLY_CH = "tg.owner_reply"
SESSION_CLOSE_CH = "tg.session_close"


def _loads_redis_json(data):
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", "ignore")
    return json.loads(data)


async def chat_bus_loop():
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(OWNER_REPLY_CH, SESSION_CLOSE_CH)

    try:
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue

            channel = msg.get("channel")
            data = msg.get("data")

            if isinstance(channel, (bytes, bytearray)):
                channel = channel.decode("utf-8", "ignore")

            try:
                payload = _loads_redis_json(data)
            except Exception:
                continue

            if channel == OWNER_REPLY_CH:
                await _handle_owner_reply(payload)

            elif channel == SESSION_CLOSE_CH:
                await _handle_session_close(payload)

    finally:
        await pubsub.close()


async def _handle_owner_reply(payload: dict):
    session_id = int(payload["sessionId"])
    text = (payload.get("text") or "").strip()
    if not text:
        return

    async with SessionLocal() as db:
        s = await db.get(ChatSession, session_id)
        if not s or s.status == SessionStatus.closed:
            return

        m = ChatMessage(session_id=session_id, sender="owner", text=text)
        db.add(m)
        await db.commit()
        await db.refresh(m)

        await ws_manager.send(s.client_id, {
            "type": "message",
            "sessionId": session_id,
            "sender": "owner",
            "text": text,
            "createdAt": m.created_at.isoformat(),
        })


async def _handle_session_close(payload: dict):
    session_id = int(payload["sessionId"])
    reason = payload.get("reason", "closed")

    async with SessionLocal() as db:
        s = await db.get(ChatSession, session_id)
        if not s:
            return

        if s.status != SessionStatus.closed:
            s.status = SessionStatus.closed
            s.closed_at = func.now()
            await db.commit()

        await ws_manager.send(s.client_id, {
            "type": "session_closed",
            "sessionId": session_id,
            "reason": reason,
        })
