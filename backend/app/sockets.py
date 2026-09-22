"""Socket.IO server for live detection alerts.

Clients authenticate with the same JWT as the REST API (auth={"token": ...})
and must join a session room explicitly; joining is authorized per session
(a teacher only for sessions they invigilate). Students cannot connect.

AsyncRedisManager routes emits through Redis pub/sub so another process
(e.g. a future worker) can emit too; with a single API replica it is not
needed for fan-out.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import jwt
import socketio
from redis.exceptions import RedisError

from app.config import settings
from app.db import acquire_connection
from app.models import Role
from app.security import decode_access_token
from app.services.authorization import can_access_session

logger = logging.getLogger("proctorai.sockets")

EVENT_DETECTION_NEW = "detection:new"
EVENT_JOIN_SESSION = "join_session"

sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=socketio.AsyncRedisManager(settings.redis_url),
    # An empty list would disable origin checks entirely; None means same-origin only.
    cors_allowed_origins=settings.cors_origins or None,
)


def session_room(session_id: str) -> str:
    return f"session:{session_id}"


@sio.event
async def connect(sid: str, environ: dict[str, Any], auth: Any) -> None:
    token = auth.get("token") if isinstance(auth, dict) else None
    if not token:
        raise socketio.exceptions.ConnectionRefusedError("authentication required")
    try:
        payload = decode_access_token(token)
        role = Role(payload["role"])
        user_id = str(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise socketio.exceptions.ConnectionRefusedError("invalid token") from exc
    if role == Role.STUDENT:
        raise socketio.exceptions.ConnectionRefusedError("not permitted")
    await sio.save_session(sid, {"user_id": user_id, "role": role.value})


@sio.on(EVENT_JOIN_SESSION)
async def join_session(sid: str, data: Any) -> dict[str, Any]:
    raw_session_id = data.get("session_id") if isinstance(data, dict) else None
    try:
        session_id = str(uuid.UUID(str(raw_session_id)))
    except ValueError:
        return {"ok": False, "error": "invalid_session_id"}

    user = await sio.get_session(sid)
    async with acquire_connection() as conn:
        row = await conn.fetchrow("SELECT invigilator_id FROM exam_sessions WHERE id = $1", session_id)
    if row is None:
        return {"ok": False, "error": "not_found"}

    invigilator_id = str(row["invigilator_id"]) if row["invigilator_id"] is not None else None
    if not can_access_session(role=Role(user["role"]), user_id=user["user_id"], invigilator_id=invigilator_id):
        return {"ok": False, "error": "forbidden"}

    await sio.enter_room(sid, session_room(session_id))
    return {"ok": True}


async def emit_detection(session_id: str, payload: dict[str, Any]) -> None:
    """Best effort: the case is already committed, so a Redis hiccup must not fail the request."""
    try:
        await sio.emit(EVENT_DETECTION_NEW, payload, room=session_room(session_id))
    except (RedisError, OSError):
        logger.exception("socket.io emit failed for session %s", session_id)
