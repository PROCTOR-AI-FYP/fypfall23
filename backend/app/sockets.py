"""Socket.IO server for live detection alerts.

Clients authenticate with the same httpOnly session cookie as the REST API
(the browser sends it on the handshake; JS never handles the token), and the
account is re-checked against the users table exactly as deps does. They
must join a session room explicitly; joining is authorized per session (a
teacher only for sessions they invigilate). Students receive opaque change
notifications only; they cannot join exam rooms or receive detection alerts.
Cross-site WebSocket hijacking is blocked by the Origin check below
(cors_allowed_origins), since cookies ride along on cross-origin handshakes.

AsyncRedisManager routes emits through Redis pub/sub so another process
(e.g. a future worker) can emit too; with a single API replica it is not
needed for fan-out.
"""
from __future__ import annotations

import logging
import uuid
from http.cookies import CookieError, SimpleCookie
from typing import Any

import socketio
from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.db import acquire_connection
from app.deps import resolve_session_user
from app.models import Role
from app.services.authorization import can_access_session

logger = logging.getLogger("proctorai.sockets")

EVENT_ALERT_NEW = "alert:new"
EVENT_JOIN_SESSION = "join_session"

sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=socketio.AsyncRedisManager(settings.redis_url),
    # An empty list would disable origin checks entirely; None means same-origin only.
    cors_allowed_origins=settings.cors_origins or None,
)


def session_room(session_id: str) -> str:
    return f"session:{session_id}"


def invigilator_room(user_id: str) -> str:
    """Every alert from any session this teacher invigilates (the Alert Inbox)."""
    return f"invigilator:{user_id}"


def _session_token(environ: dict[str, Any]) -> str | None:
    cookies = SimpleCookie()
    try:
        cookies.load(environ.get("HTTP_COOKIE", ""))
    except CookieError:
        return None
    morsel = cookies.get(settings.session_cookie_name)
    return morsel.value if morsel is not None else None


@sio.event
async def connect(sid: str, environ: dict[str, Any], auth: Any) -> None:
    try:
        async with acquire_connection() as conn:
            user = await resolve_session_user(conn, _session_token(environ))
    except HTTPException as exc:
        raise socketio.exceptions.ConnectionRefusedError("authentication required") from exc
    await sio.save_session(sid, {"user_id": user.user_id, "role": user.role.value,'token':_session_token(environ)})
    await sio.enter_room(sid, f'user:{user.user_id}')
    await sio.enter_room(sid, 'sync:authenticated')
    if user.role == Role.TEACHER:
        await sio.enter_room(sid, invigilator_room(user.user_id))


@sio.on(EVENT_JOIN_SESSION)
async def join_session(sid: str, data: Any) -> dict[str, Any]:
    raw_session_id = data.get("session_id") if isinstance(data, dict) else None
    try:
        session_id = str(uuid.UUID(str(raw_session_id)))
    except ValueError:
        return {"ok": False, "error": "invalid_session_id"}

    user = await sio.get_session(sid)
    async with acquire_connection() as conn:
        try:
            resolved = await resolve_session_user(conn,user['token'])
        except HTTPException:
            return {'ok':False,'error':'forbidden'}
        row = await conn.fetchrow("SELECT invigilator_id FROM exam_sessions WHERE id = $1", session_id)
    if row is None:
        return {"ok": False, "error": "not_found"}

    invigilator_id = str(row["invigilator_id"]) if row["invigilator_id"] is not None else None
    if not can_access_session(role=resolved.role, user_id=resolved.user_id, invigilator_id=invigilator_id):
        return {"ok": False, "error": "forbidden"}

    await sio.enter_room(sid, session_room(session_id))
    return {"ok": True}


async def emit_detection(session_id: str, invigilator_id: str | None, payload: dict[str, Any]) -> None:
    """Best effort: the case is already committed, so a Redis hiccup must not fail the request.

    Sent to everyone watching the session and to the invigilator's own room;
    a client in both receives it once.
    """
    rooms = [session_room(session_id)] + ([invigilator_room(invigilator_id)] if invigilator_id else [])
    try:
        # A room subscription must not outlive its account or exam assignment.
        recipients = {sid for room in rooms for sid,_ in sio.manager.get_participants('/',room)}
        for sid in recipients:
            try:
                session = await sio.get_session(sid)
                async with acquire_connection() as conn:
                    current = await resolve_session_user(conn,session.get('token'))
                    assigned = await conn.fetchval('SELECT invigilator_id FROM exam_sessions WHERE id=$1::uuid',session_id)
                if not can_access_session(role=current.role,user_id=current.user_id,invigilator_id=str(assigned) if assigned else None):
                    await sio.disconnect(sid)
            except HTTPException:
                await sio.disconnect(sid)
            except KeyError:
                # The connection disappeared during the permission check.
                continue
        await sio.emit(EVENT_ALERT_NEW, payload, to=rooms)
    except (RedisError, OSError):
        logger.exception("socket.io emit failed for session %s", session_id)


async def emit_sync() -> None:
    """Opaque invalidation only. Each screen re-reads its authorized REST data.

    No case identifier, person, score, or evidence is broadcast to this room.
    """
    try:
        await sio.emit('sync:changed', {}, to='sync:authenticated')
    except (RedisError,OSError):
        logger.exception('live refresh notification failed')


async def revoke_user_connections(user_id: str) -> None:
    for sid,_ in list(sio.manager.get_participants('/',f'user:{user_id}')):
        await sio.disconnect(sid)
