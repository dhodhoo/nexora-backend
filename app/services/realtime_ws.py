import asyncio
import time
from collections import defaultdict
from typing import DefaultDict

from fastapi import WebSocket

from app.database import SessionLocal
from app.services.dashboard import build_dashboard_snapshot, build_unit_dashboard_snapshot


class CommunityDashboardWSManager:
    def __init__(self, min_interval_ms: int = 500):
        self._connections: DefaultDict[str, set[WebSocket]] = defaultdict(set)
        self._unit_connections: DefaultDict[tuple[str, str], set[WebSocket]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._min_interval_seconds = max(0.1, min_interval_ms / 1000.0)
        self._last_emit: dict[str, float] = {}
        self._last_unit_emit: dict[tuple[str, str], float] = {}
        self._pending: dict[str, bool] = {}
        self._pending_unit: dict[tuple[str, str], bool] = {}
        self._locks: DefaultDict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._unit_locks: DefaultDict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def has_connections(self, community_id: str) -> bool:
        return bool(self._connections.get(community_id))

    async def connect(self, community_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[community_id].add(websocket)

    async def disconnect(self, community_id: str, websocket: WebSocket) -> None:
        conns = self._connections.get(community_id)
        if conns and websocket in conns:
            conns.remove(websocket)
            if not conns:
                self._connections.pop(community_id, None)

    async def connect_unit(self, community_id: str, unit_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._unit_connections[(community_id, unit_id)].add(websocket)

    async def disconnect_unit(self, community_id: str, unit_id: str, websocket: WebSocket) -> None:
        key = (community_id, unit_id)
        conns = self._unit_connections.get(key)
        if conns and websocket in conns:
            conns.remove(websocket)
            if not conns:
                self._unit_connections.pop(key, None)

    async def send_snapshot(self, websocket: WebSocket, community_id: str) -> bool:
        db = SessionLocal()
        try:
            snapshot = build_dashboard_snapshot(db, community_id)
        finally:
            db.close()

        if snapshot is None:
            return False

        await websocket.send_json(
            {
                "type": "dashboard_snapshot",
                "community_id": community_id,
                "data": snapshot.model_dump(mode="json"),
            }
        )
        return True

    async def send_unit_snapshot(self, websocket: WebSocket, community_id: str, unit_id: str) -> bool:
        db = SessionLocal()
        try:
            snapshot = build_unit_dashboard_snapshot(db, community_id, unit_id)
        finally:
            db.close()
        if snapshot is None:
            return False
        await websocket.send_json(
            {
                "type": "unit_dashboard_snapshot",
                "community_id": community_id,
                "unit_id": unit_id,
                "data": snapshot.model_dump(mode="json"),
            }
        )
        return True

    async def _broadcast_snapshot(self, community_id: str) -> None:
        conns = list(self._connections.get(community_id, set()))
        if not conns:
            return

        db = SessionLocal()
        try:
            snapshot = build_dashboard_snapshot(db, community_id)
        finally:
            db.close()
        if snapshot is None:
            return

        payload = {
            "type": "dashboard_snapshot",
            "community_id": community_id,
            "data": snapshot.model_dump(mode="json"),
        }
        to_remove: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:
                to_remove.append(ws)

        if to_remove:
            active = self._connections.get(community_id, set())
            for ws in to_remove:
                if ws in active:
                    active.remove(ws)
            if not active:
                self._connections.pop(community_id, None)

    async def _debounced_broadcast(self, community_id: str) -> None:
        async with self._locks[community_id]:
            now = time.monotonic()
            last = self._last_emit.get(community_id, 0.0)
            wait = self._min_interval_seconds - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)

            await self._broadcast_snapshot(community_id)
            self._last_emit[community_id] = time.monotonic()
            self._pending[community_id] = False

    async def _broadcast_unit_snapshot(self, community_id: str, unit_id: str) -> None:
        key = (community_id, unit_id)
        conns = list(self._unit_connections.get(key, set()))
        if not conns:
            return
        db = SessionLocal()
        try:
            snapshot = build_unit_dashboard_snapshot(db, community_id, unit_id)
        finally:
            db.close()
        if snapshot is None:
            return
        payload = {
            "type": "unit_dashboard_snapshot",
            "community_id": community_id,
            "unit_id": unit_id,
            "data": snapshot.model_dump(mode="json"),
        }
        to_remove: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:
                to_remove.append(ws)
        if to_remove:
            active = self._unit_connections.get(key, set())
            for ws in to_remove:
                if ws in active:
                    active.remove(ws)
            if not active:
                self._unit_connections.pop(key, None)

    async def _debounced_unit_broadcast(self, community_id: str, unit_id: str) -> None:
        key = (community_id, unit_id)
        async with self._unit_locks[key]:
            now = time.monotonic()
            last = self._last_unit_emit.get(key, 0.0)
            wait = self._min_interval_seconds - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            await self._broadcast_unit_snapshot(community_id, unit_id)
            self._last_unit_emit[key] = time.monotonic()
            self._pending_unit[key] = False

    def notify_community_update(self, community_id: str) -> None:
        if not self.has_connections(community_id):
            return
        if not self._loop or self._loop.is_closed():
            return
        if self._pending.get(community_id):
            return
        self._pending[community_id] = True
        coro = self._debounced_broadcast(community_id)
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except Exception:
            self._pending[community_id] = False
            coro.close()

    def notify_unit_update(self, community_id: str, unit_id: str) -> None:
        key = (community_id, unit_id)
        if not self._unit_connections.get(key):
            return
        if not self._loop or self._loop.is_closed():
            return
        if self._pending_unit.get(key):
            return
        self._pending_unit[key] = True
        coro = self._debounced_unit_broadcast(community_id, unit_id)
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except Exception:
            self._pending_unit[key] = False
            coro.close()


dashboard_ws_manager = CommunityDashboardWSManager()
