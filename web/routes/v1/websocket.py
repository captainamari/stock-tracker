"""
API v1: WebSocket Endpoint
============================
Real-time WebSocket for pushing signals, score updates, and refresh progress.

Channels:
    signals      — New trading signals (entry/exit/warning)
    scores       — Score updates after computation
    refresh      — Pipeline refresh progress

Protocol:
    Client → Server: {"type": "subscribe", "channels": ["signals", "scores"]}
    Client → Server: {"type": "ping"}
    Server → Client: {"type": "signal", "data": {...}}
    Server → Client: {"type": "score_update", "data": {...}}
    Server → Client: {"type": "refresh_progress", "data": {...}}
    Server → Client: {"type": "pong"}
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages active WebSocket connections and message broadcasting."""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "signals": set(),
            "scores": set(),
            "refresh": set(),
            "all": set(),
        }
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, channels: List[str] = None):
        """Accept connection and register to channels."""
        await websocket.accept()
        channels = channels or ["all"]
        async with self._lock:
            self.active_connections["all"].add(websocket)
            for ch in channels:
                if ch in self.active_connections:
                    self.active_connections[ch].add(websocket)

    async def disconnect(self, websocket: WebSocket):
        """Remove connection from all channels."""
        async with self._lock:
            for channel_set in self.active_connections.values():
                channel_set.discard(websocket)

    async def broadcast(self, channel: str, message: Dict[str, Any]):
        """Send message to all connections subscribed to a channel."""
        targets = self.active_connections.get(channel, set()) | self.active_connections.get("all", set())
        dead = set()
        for conn in targets:
            try:
                await conn.send_json(message)
            except Exception:
                dead.add(conn)
        # Clean dead connections
        if dead:
            async with self._lock:
                for channel_set in self.active_connections.values():
                    channel_set -= dead

    async def send_personal(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send message to a specific connection."""
        try:
            await websocket.send_json(message)
        except Exception:
            await self.disconnect(websocket)

    @property
    def connection_count(self) -> int:
        return len(self.active_connections["all"])


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.

    Clients can subscribe to specific channels by sending:
        {"type": "subscribe", "channels": ["signals", "scores"]}
    """
    await manager.connect(websocket)
    logger.info(f"WebSocket connected. Total: {manager.connection_count}")

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await manager.send_personal(websocket, {"type": "pong", "ts": time.time()})

                elif msg_type == "subscribe":
                    channels = msg.get("channels", [])
                    async with manager._lock:
                        for ch in channels:
                            if ch in manager.active_connections:
                                manager.active_connections[ch].add(websocket)
                    await manager.send_personal(websocket, {
                        "type": "subscribed",
                        "channels": channels,
                    })

                elif msg_type == "unsubscribe":
                    channels = msg.get("channels", [])
                    async with manager._lock:
                        for ch in channels:
                            if ch in manager.active_connections:
                                manager.active_connections[ch].discard(websocket)
                    await manager.send_personal(websocket, {
                        "type": "unsubscribed",
                        "channels": channels,
                    })

                else:
                    await manager.send_personal(websocket, {
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    })

            except json.JSONDecodeError:
                await manager.send_personal(websocket, {
                    "type": "error",
                    "message": "Invalid JSON",
                })

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        logger.info(f"WebSocket disconnected. Total: {manager.connection_count}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)


# ── Broadcast Helpers (called from other modules) ──

async def broadcast_signal(signal_data: Dict[str, Any]):
    """Broadcast a new signal to all connected clients."""
    await manager.broadcast("signals", {
        "type": "signal",
        "data": signal_data,
        "ts": time.time(),
    })


async def broadcast_score_update(scores_data: List[Dict[str, Any]]):
    """Broadcast score updates after computation."""
    await manager.broadcast("scores", {
        "type": "score_update",
        "data": scores_data,
        "ts": time.time(),
    })


async def broadcast_refresh_progress(progress_data: Dict[str, Any]):
    """Broadcast pipeline refresh progress."""
    await manager.broadcast("refresh", {
        "type": "refresh_progress",
        "data": progress_data,
        "ts": time.time(),
    })


# ── Status endpoint ──

@router.get("/ws/status")
async def ws_status():
    """Get WebSocket connection status."""
    return {
        "connections": manager.connection_count,
        "channels": {
            ch: len(conns) for ch, conns in manager.active_connections.items()
        },
    }
