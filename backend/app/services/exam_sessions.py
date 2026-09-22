"""Exam-session metadata lookups with a short in-process cache.

The detection worker posts a frame roughly six times a second per room; a
DB round trip per frame just to learn the session's status and silent-mode
flag is wasted work. The service runs as a single replica, so an in-process
cache is coherent; status changes take effect within the TTL.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import asyncpg

from app.models import ExamSessionStatus

SESSION_META_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class SessionMeta:
    id: str
    course_code: str
    room: str
    status: ExamSessionStatus
    silent_mode: bool
    invigilator_id: str | None

    @property
    def is_active(self) -> bool:
        return self.status == ExamSessionStatus.IN_PROGRESS


_cache: dict[str, tuple[float, SessionMeta]] = {}


async def get_session_meta(conn: asyncpg.Connection, session_id: str) -> SessionMeta | None:
    now = time.monotonic()
    cached = _cache.get(session_id)
    if cached is not None and cached[0] > now:
        return cached[1]

    row = await conn.fetchrow(
        "SELECT id, course_code, room, status, silent_mode, invigilator_id FROM exam_sessions WHERE id = $1",
        session_id,
    )
    if row is None:
        return None

    meta = SessionMeta(
        id=str(row["id"]),
        course_code=row["course_code"],
        room=row["room"],
        status=ExamSessionStatus(row["status"]),
        silent_mode=row["silent_mode"],
        invigilator_id=str(row["invigilator_id"]) if row["invigilator_id"] is not None else None,
    )
    _cache[session_id] = (now + SESSION_META_TTL_SECONDS, meta)
    return meta


def clear_session_meta_cache() -> None:
    _cache.clear()
