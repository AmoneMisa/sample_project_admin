import asyncio
from typing import Dict, Set
from fastapi import WebSocket

class WSManager:
    def __init__(self):
        self._conns: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, client_id: str, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._conns.setdefault(client_id, set()).add(ws)

    async def disconnect(self, client_id: str, ws: WebSocket):
        async with self._lock:
            conns = self._conns.get(client_id)
            if not conns:
                return
            conns.discard(ws)
            if not conns:
                self._conns.pop(client_id, None)

    async def send(self, client_id: str, payload: dict):
        async with self._lock:
            conns = list(self._conns.get(client_id, set()))
        dead = []
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(client_id, ws)

ws_manager = WSManager()
