"""Exam scheduling and invigilator assignment (Exam Controller; Admin too).

A scheduled exam is an exam_sessions row with status 'scheduled'. Room
clashes are allowed but flagged (has_conflict), as the schedule screen shows
them; double-booking an invigilator is refused outright.
"""
from __future__ import annotations

from datetime import date, time
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import (
    ACTION_EXAM_CANCELLED,
    ACTION_EXAM_SCHEDULED,
    ACTION_EXAM_UPDATED,
    ACTION_INVIGILATOR_ASSIGNED,
    record_audit,
)
from app.deps import CurrentUser, get_client_ip, get_db, require_role
from app.models import ExamSessionStatus, NotificationType, Role
from app.schemas import (
    AssignInvigilatorRequest,
    ExamScheduleCreate,
    ExamScheduleOut,
    ExamScheduleUpdate,
    InvigilatorAssignmentOut,
)
from app.services.clock import hhmm, institution_today
from app.services.notifications import notify_users

router = APIRouter(tags=["schedule"])

require_scheduler = require_role(Role.EXAM_CONTROLLER, Role.ADMIN)
ERR_NOT_FOUND = "Scheduled exam not found."

# Another live exam overlapping in time on the same day, in the same room or
# with the same invigilator.
CONFLICT_SQL = """
    SELECT other.course_code, other.room,
           (other.classroom_id = s.classroom_id) AS same_room
    FROM exam_sessions other
    WHERE other.id <> s.id
      AND other.status IN ('scheduled', 'in_progress')
      AND other.scheduled_date = s.scheduled_date
      AND other.start_time < s.end_time AND s.start_time < other.end_time
      AND (other.classroom_id = s.classroom_id
           OR (s.invigilator_id IS NOT NULL AND other.invigilator_id = s.invigilator_id))
    ORDER BY other.start_time
    LIMIT 1
"""

SCHEDULE_SELECT = f"""
    SELECT s.id, s.course_code, s.course_name, s.department, s.scheduled_date, s.start_time, s.end_time,
           s.classroom_id, s.room, s.invigilator_id, inv.full_name AS invigilator_name, s.status,
           conflict.course_code AS conflict_course, conflict.room AS conflict_room, conflict.same_room
    FROM exam_sessions s
    LEFT JOIN users inv ON inv.id = s.invigilator_id
    LEFT JOIN LATERAL ({CONFLICT_SQL}) conflict ON true
"""


def _row_to_entry(row: asyncpg.Record) -> ExamScheduleOut:
    details = None
    if row["conflict_course"] is not None:
        where = f"in {row['conflict_room']}" if row["same_room"] else "with the same invigilator"
        details = f"Overlaps {row['conflict_course']} {where}"
    return ExamScheduleOut(
        id=str(row["id"]),
        course_code=row["course_code"],
        course_name=row["course_name"],
        department=row["department"],
        date=row["scheduled_date"],
        start_time=hhmm(row["start_time"]),
        end_time=hhmm(row["end_time"]),
        classroom_id=str(row["classroom_id"]) if row["classroom_id"] else None,
        classroom_name=row["room"],
        invigilator_id=str(row["invigilator_id"]) if row["invigilator_id"] else None,
        invigilator_name=row["invigilator_name"],
        status=ExamSessionStatus(row["status"]),
        has_conflict=details is not None,
        conflict_details=details,
    )


def _validate_slot(exam_date: date, start: time, end: time) -> None:
    if end <= start:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The exam must end after it starts.")
    if exam_date < institution_today():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="An exam cannot be scheduled in the past.")


async def _classroom_name(conn: asyncpg.Connection, classroom_id: UUID) -> str:
    name = await conn.fetchval("SELECT name FROM classrooms WHERE id = $1", classroom_id)
    if name is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown classroom.")
    return name


async def _entry(conn: asyncpg.Connection, exam_id: str) -> ExamScheduleOut:
    return _row_to_entry(await conn.fetchrow(f"{SCHEDULE_SELECT} WHERE s.id = $1::uuid", exam_id))


@router.get("/api/exam-schedule", response_model=list[ExamScheduleOut])
async def list_schedule(
    current_user: CurrentUser = Depends(require_scheduler),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[ExamScheduleOut]:
    rows = await conn.fetch(
        f"{SCHEDULE_SELECT} WHERE s.status = 'scheduled' ORDER BY s.scheduled_date, s.start_time, s.course_code"
    )
    return [_row_to_entry(row) for row in rows]


@router.post("/api/exam-schedule", response_model=ExamScheduleOut, status_code=status.HTTP_201_CREATED)
async def schedule_exam(
    body: ExamScheduleCreate,
    request: Request,
    current_user: CurrentUser = Depends(require_scheduler),
    conn: asyncpg.Connection = Depends(get_db),
) -> ExamScheduleOut:
    _validate_slot(body.date, body.start_time, body.end_time)
    async with conn.transaction():
        room = await _classroom_name(conn, body.classroom_id)
        exam_id = await conn.fetchval(
            """
            INSERT INTO exam_sessions (course_code, course_name, department, classroom_id, room,
                                       scheduled_date, start_time, end_time, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'scheduled')
            RETURNING id
            """,
            body.course_code.strip().upper(),
            body.course_name.strip(),
            body.department.strip(),
            body.classroom_id,
            room,
            body.date,
            body.start_time,
            body.end_time,
        )
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_EXAM_SCHEDULED,
            target=str(exam_id),
            new_value={"course_code": body.course_code.strip().upper(), "date": body.date.isoformat(), "room": room,
                       "start": hhmm(body.start_time), "end": hhmm(body.end_time)},
            ip_address=get_client_ip(request),
        )
    return await _entry(conn, str(exam_id))


@router.patch("/api/exam-schedule/{exam_id}", response_model=ExamScheduleOut)
async def update_exam(
    exam_id: UUID,
    body: ExamScheduleUpdate,
    request: Request,
    current_user: CurrentUser = Depends(require_scheduler),
    conn: asyncpg.Connection = Depends(get_db),
) -> ExamScheduleOut:
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    async with conn.transaction():
        exam = await conn.fetchrow("SELECT * FROM exam_sessions WHERE id = $1 FOR UPDATE", exam_id)
        if exam is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
        if exam["status"] != ExamSessionStatus.SCHEDULED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only an exam that has not started can be changed.")
        new_date = changes.get("date", exam["scheduled_date"])
        new_start = changes.get("start_time", exam["start_time"])
        new_end = changes.get("end_time", exam["end_time"])
        if new_date is None or new_start is None or new_end is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="An exam needs a date, start and end time.")
        _validate_slot(new_date, new_start, new_end)
        classroom_id = changes.get("classroom_id", exam["classroom_id"])
        room = await _classroom_name(conn, classroom_id) if "classroom_id" in changes else exam["room"]
        await conn.execute(
            """
            UPDATE exam_sessions SET course_code = $2, course_name = $3, department = $4, classroom_id = $5, room = $6,
                                     scheduled_date = $7, start_time = $8, end_time = $9
            WHERE id = $1
            """,
            exam_id,
            changes.get("course_code", exam["course_code"]).strip().upper(),
            changes.get("course_name", exam["course_name"]).strip(),
            changes.get("department", exam["department"]).strip(),
            classroom_id,
            room,
            new_date,
            new_start,
            new_end,
        )
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_EXAM_UPDATED,
            target=str(exam_id),
            new_value={key: (str(value) if not isinstance(value, str) else value) for key, value in changes.items()},
            ip_address=get_client_ip(request),
        )
    return await _entry(conn, str(exam_id))


@router.delete("/api/exam-schedule/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_exam(
    exam_id: UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_scheduler),
    conn: asyncpg.Connection = Depends(get_db),
) -> None:
    async with conn.transaction():
        cancelled = await conn.fetchval(
            "UPDATE exam_sessions SET status = 'cancelled' WHERE id = $1 AND status = 'scheduled' RETURNING id", exam_id
        )
        if cancelled is None:
            exists = await conn.fetchval("SELECT 1 FROM exam_sessions WHERE id = $1", exam_id)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT if exists else status.HTTP_404_NOT_FOUND,
                detail="Only an exam that has not started can be cancelled." if exists else ERR_NOT_FOUND,
            )
        await record_audit(
            conn, actor_id=current_user.user_id, action=ACTION_EXAM_CANCELLED, target=str(exam_id),
            new_value={}, ip_address=get_client_ip(request),
        )


@router.get("/api/invigilator-assignments", response_model=list[InvigilatorAssignmentOut])
async def list_assignments(
    current_user: CurrentUser = Depends(require_scheduler),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[InvigilatorAssignmentOut]:
    rows = await conn.fetch(
        """
        SELECT s.id, s.course_code, s.scheduled_date, s.start_time, s.end_time, s.room,
               u.id AS teacher_id, u.full_name AS teacher_name, u.department
        FROM exam_sessions s JOIN users u ON u.id = s.invigilator_id
        WHERE s.status IN ('scheduled', 'in_progress')
        ORDER BY s.scheduled_date, s.start_time
        """
    )
    return [
        InvigilatorAssignmentOut(
            id=str(row["id"]),
            exam_id=str(row["id"]),
            teacher_id=str(row["teacher_id"]),
            teacher_name=row["teacher_name"],
            department=row["department"],
            course_code=row["course_code"],
            date=row["scheduled_date"],
            start_time=hhmm(row["start_time"]),
            end_time=hhmm(row["end_time"]),
            classroom_name=row["room"],
        )
        for row in rows
    ]


@router.post("/api/exam-schedule/{exam_id}/invigilator", response_model=InvigilatorAssignmentOut)
async def assign_invigilator(
    exam_id: UUID,
    body: AssignInvigilatorRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_scheduler),
    conn: asyncpg.Connection = Depends(get_db),
) -> InvigilatorAssignmentOut:
    async with conn.transaction():
        exam = await conn.fetchrow(
            "SELECT course_code, scheduled_date, start_time, end_time, room, status FROM exam_sessions WHERE id = $1 FOR UPDATE",
            exam_id,
        )
        if exam is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
        if exam["status"] != ExamSessionStatus.SCHEDULED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invigilators can only be assigned before the exam starts.")
        teacher = await conn.fetchrow(
            """
            SELECT id, full_name, department FROM users
            WHERE id = $1 AND role = 'teacher' AND status = 'active' AND deleted_at IS NULL
            """,
            body.teacher_id,
        )
        if teacher is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Choose an active teacher account.")
        clash = await conn.fetchval(
            """
            SELECT course_code FROM exam_sessions
            WHERE id <> $1 AND invigilator_id = $2 AND status IN ('scheduled', 'in_progress')
              AND scheduled_date = $3 AND start_time < $5 AND $4 < end_time
            LIMIT 1
            """,
            exam_id, body.teacher_id, exam["scheduled_date"], exam["start_time"], exam["end_time"],
        )
        if clash is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{teacher['full_name']} is already invigilating {clash} at that time.")
        await conn.execute("UPDATE exam_sessions SET invigilator_id = $2 WHERE id = $1", exam_id, body.teacher_id)
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_INVIGILATOR_ASSIGNED,
            target=str(exam_id),
            new_value={"teacher_id": str(body.teacher_id), "course_code": exam["course_code"]},
            ip_address=get_client_ip(request),
        )
        await notify_users(
            conn, [str(body.teacher_id)], type_=NotificationType.SYSTEM,
            title=f"Invigilation assigned: {exam['course_code']}",
            message=f"{exam['scheduled_date']:%d %b %Y}, {hhmm(exam['start_time'])}-{hhmm(exam['end_time'])} in {exam['room']}.",
            reference_type="session", reference_id=str(exam_id),
        )
    return InvigilatorAssignmentOut(
        id=str(exam_id),
        exam_id=str(exam_id),
        teacher_id=str(teacher["id"]),
        teacher_name=teacher["full_name"],
        department=teacher["department"],
        course_code=exam["course_code"],
        date=exam["scheduled_date"],
        start_time=hhmm(exam["start_time"]),
        end_time=hhmm(exam["end_time"]),
        classroom_name=exam["room"],
    )
