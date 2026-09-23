"""Exam-session read model, plus metadata lookups with a short in-process cache.

The detection worker posts a frame roughly six times a second per room; a
DB round trip per frame just to learn the session's status and silent-mode
flag is wasted work. The service runs as a single replica, so an in-process
cache is coherent. Routes that change a session's status or silent mode call
forget_session_meta, so an ended session stops accepting detections at once
rather than after the TTL.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import asyncpg

from app.models import ExamSessionStatus
from app.schemas import ExamSessionOut
from app.services.clock import hhmm

SESSION_SELECT = """
    SELECT s.id, s.course_code, s.course_name, s.department, s.classroom_id, s.room, s.scheduled_date,
           s.start_time, s.end_time, s.status, s.invigilator_id, inv.full_name AS invigilator_name,
           s.silent_mode, s.started_at, s.ended_at, s.created_at, cl.capacity,
           (SELECT count(*) FROM seat_assignments sa WHERE sa.session_id = s.id AND sa.student_id IS NOT NULL)
               AS occupied_seats,
           (SELECT max(sa.seat_number) FROM seat_assignments sa WHERE sa.session_id = s.id) AS max_seat,
           (SELECT count(*) FROM detection_events de WHERE de.session_id = s.id) AS alert_count,
           (SELECT count(*) FROM cases c WHERE c.session_id = s.id) AS case_count,
           (SELECT count(*) FROM cases c WHERE c.session_id = s.id AND c.status = 'confirmed') AS confirmed_case_count
    FROM exam_sessions s
    LEFT JOIN users inv ON inv.id = s.invigilator_id
    LEFT JOIN classrooms cl ON cl.id = s.classroom_id
"""


def row_to_session(row: asyncpg.Record) -> ExamSessionOut:
    return ExamSessionOut(
        id=str(row["id"]),
        course_code=row["course_code"],
        course_name=row["course_name"],
        department=row["department"],
        classroom_id=str(row["classroom_id"]) if row["classroom_id"] else None,
        classroom_name=row["room"],
        scheduled_date=row["scheduled_date"],
        start_time=hhmm(row["start_time"]),
        end_time=hhmm(row["end_time"]),
        status=ExamSessionStatus(row["status"]),
        invigilator_id=str(row["invigilator_id"]) if row["invigilator_id"] else None,
        invigilator_name=row["invigilator_name"],
        silent_mode=row["silent_mode"],
        total_seats=row["capacity"] or row["max_seat"] or 0,
        occupied_seats=row["occupied_seats"],
        alert_count=row["alert_count"],
        case_count=row["case_count"],
        confirmed_case_count=row["confirmed_case_count"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        created_at=row["created_at"],
    )

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


def forget_session_meta(session_id: str) -> None:
    _cache.pop(session_id, None)


def clear_session_meta_cache() -> None:
    _cache.clear()
