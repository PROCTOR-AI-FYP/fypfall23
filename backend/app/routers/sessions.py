"""Exam sessions: listing, starting and ending, and the seat map.

A teacher starts the exam they were assigned to (scheduled for today in the
classroom they pick); the seat map is the join between an activated student
account and a seat. A row that doesn't resolve is reported back, never
silently skipped and never used to create an account.
"""
from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from app.audit import ACTION_SEATMAP_UPLOAD, ACTION_SESSION_ENDED, ACTION_SESSION_STARTED, record_audit
from app.deps import CurrentUser, get_client_ip, get_db, require_role
from app.models import ExamSessionStatus, Role, SeatmapRowStatus
from app.schemas import ExamSessionOut, SeatmapUploadResponse
from app.services.authorization import can_access_session
from app.services.clock import institution_now
from app.services.exam_sessions import SESSION_SELECT, forget_session_meta, row_to_session
from app.services.seatmap import (
    MAX_SEATMAP_BYTES,
    SeatmapError,
    parse_seatmap,
    replace_seat_assignments,
    resolve_seatmap,
    summarize,
)

router = APIRouter(tags=["sessions"])

require_session_reader = require_role(Role.ADMIN, Role.HOD, Role.EXAM_CONTROLLER, Role.TEACHER)
require_seatmap_uploader = require_role(Role.ADMIN, Role.EXAM_CONTROLLER, Role.TEACHER)
require_session_runner = require_role(Role.ADMIN, Role.EXAM_CONTROLLER, Role.TEACHER)
require_teacher = require_role(Role.TEACHER)
ERR_NOT_FOUND = "Exam session not found."
EDITABLE_SEATMAP_STATUSES = {ExamSessionStatus.SCHEDULED.value, ExamSessionStatus.IN_PROGRESS.value}


async def _read_upload(file: UploadFile) -> bytes:
    # Bounded read: never buffer more than the limit plus one byte.
    raw = await file.read(MAX_SEATMAP_BYTES + 1)
    if len(raw) > MAX_SEATMAP_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=f"Seat map must be at most {MAX_SEATMAP_BYTES // 1024} KB.")
    return raw


async def _parse(file: UploadFile) -> list[tuple[int, str]]:
    try:
        return parse_seatmap(await _read_upload(file))
    except SeatmapError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


async def _visible_session(conn: asyncpg.Connection, session_id: UUID, current_user: CurrentUser) -> asyncpg.Record:
    row = await conn.fetchrow(f"{SESSION_SELECT} WHERE s.id = $1", session_id)
    invigilator_id = str(row["invigilator_id"]) if row is not None and row["invigilator_id"] else None
    if row is None or not can_access_session(role=current_user.role, user_id=current_user.user_id, invigilator_id=invigilator_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
    return row


@router.get("/api/sessions", response_model=list[ExamSessionOut])
async def list_sessions(
    session_status: ExamSessionStatus | None = Query(default=None, alias="status"),
    current_user: CurrentUser = Depends(require_session_reader),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[ExamSessionOut]:
    rows = await conn.fetch(
        f"""
        {SESSION_SELECT}
        WHERE ($1::text IS NULL OR s.status = $1)
          AND ($2::uuid IS NULL OR s.invigilator_id = $2::uuid)
        ORDER BY s.scheduled_date DESC NULLS LAST, s.start_time DESC NULLS LAST, s.created_at DESC
        """,
        session_status.value if session_status else None,
        current_user.user_id if current_user.role == Role.TEACHER else None,
    )
    return [row_to_session(row) for row in rows]


@router.get("/api/sessions/{session_id}", response_model=ExamSessionOut)
async def get_session(
    session_id: UUID,
    current_user: CurrentUser = Depends(require_session_reader),
    conn: asyncpg.Connection = Depends(get_db),
) -> ExamSessionOut:
    return row_to_session(await _visible_session(conn, session_id, current_user))


@router.post("/api/seatmap/preview", response_model=SeatmapUploadResponse)
async def preview_seatmap(
    file: UploadFile,
    current_user: CurrentUser = Depends(require_seatmap_uploader),
    conn: asyncpg.Connection = Depends(get_db),
) -> SeatmapUploadResponse:
    """Resolve a CSV against registered students without writing anything."""
    return summarize(await resolve_seatmap(conn, await _parse(file)))


@router.post("/api/sessions/{session_id}/seatmap", response_model=SeatmapUploadResponse)
async def upload_seatmap(
    session_id: UUID,
    file: UploadFile,
    request: Request,
    current_user: CurrentUser = Depends(require_seatmap_uploader),
    conn: asyncpg.Connection = Depends(get_db),
) -> SeatmapUploadResponse:
    parsed = await _parse(file)
    async with conn.transaction():
        session = await conn.fetchrow("SELECT status, invigilator_id FROM exam_sessions WHERE id = $1 FOR UPDATE", session_id)
        invigilator_id = str(session["invigilator_id"]) if session is not None and session["invigilator_id"] else None
        if session is None or not can_access_session(role=current_user.role, user_id=current_user.user_id, invigilator_id=invigilator_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
        if session["status"] not in EDITABLE_SEATMAP_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The seat map of a finished or cancelled exam is part of its record and cannot change.")
        resolved = await resolve_seatmap(conn, parsed)
        await replace_seat_assignments(conn, str(session_id), resolved)
        result = summarize(resolved)
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_SEATMAP_UPLOAD,
            target=str(session_id),
            new_value={"resolved_count": result.resolved_count, "rejected_count": result.rejected_count},
            ip_address=get_client_ip(request),
        )
    return result


@router.post("/api/sessions/start", response_model=ExamSessionOut)
async def start_session(
    request: Request,
    classroom_id: UUID = Form(...),
    silent_mode: bool = Form(False),
    file: UploadFile | None = File(default=None),
    current_user: CurrentUser = Depends(require_teacher),
    conn: asyncpg.Connection = Depends(get_db),
) -> ExamSessionOut:
    """Start the exam this teacher is assigned to, in this room, today.

    With a seat map attached, it must resolve completely and is applied in
    the same transaction, so detections never run against a half-loaded map.
    """
    parsed = await _parse(file) if file is not None else None
    today = institution_now().date()
    async with conn.transaction():
        session = await conn.fetchrow(
            """
            SELECT id FROM exam_sessions
            WHERE invigilator_id = $1::uuid AND classroom_id = $2 AND scheduled_date = $3 AND status = 'scheduled'
            ORDER BY start_time NULLS LAST
            LIMIT 1
            FOR UPDATE
            """,
            current_user.user_id,
            classroom_id,
            today,
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="You have no exam scheduled in this classroom today. Check the exam schedule with the Exam Controller.",
            )
        session_id = str(session["id"])
        seat_summary = None
        if parsed is not None:
            resolved = await resolve_seatmap(conn, parsed)
            if any(row.status != SeatmapRowStatus.RESOLVED for row in resolved):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Resolve all seat assignments before starting the session.")
            await replace_seat_assignments(conn, session_id, resolved)
            seat_summary = summarize(resolved)
        await conn.execute(
            "UPDATE exam_sessions SET status = 'in_progress', silent_mode = $2, started_at = now() WHERE id = $1::uuid",
            session_id,
            silent_mode,
        )
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_SESSION_STARTED,
            target=session_id,
            new_value={"silent_mode": silent_mode, "seats_resolved": seat_summary.resolved_count if seat_summary else None},
            ip_address=get_client_ip(request),
        )
    forget_session_meta(session_id)
    return row_to_session(await conn.fetchrow(f"{SESSION_SELECT} WHERE s.id = $1::uuid", session_id))


@router.post("/api/sessions/{session_id}/end", response_model=ExamSessionOut)
async def end_session(
    session_id: UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_session_runner),
    conn: asyncpg.Connection = Depends(get_db),
) -> ExamSessionOut:
    async with conn.transaction():
        session = await conn.fetchrow("SELECT status, invigilator_id FROM exam_sessions WHERE id = $1 FOR UPDATE", session_id)
        invigilator_id = str(session["invigilator_id"]) if session is not None and session["invigilator_id"] else None
        if session is None or not can_access_session(role=current_user.role, user_id=current_user.user_id, invigilator_id=invigilator_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
        if session["status"] != ExamSessionStatus.IN_PROGRESS.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only an exam in progress can be ended.")
        await conn.execute("UPDATE exam_sessions SET status = 'completed', ended_at = now() WHERE id = $1", session_id)
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_SESSION_ENDED,
            target=str(session_id),
            new_value={},
            ip_address=get_client_ip(request),
        )
    forget_session_meta(str(session_id))
    return row_to_session(await conn.fetchrow(f"{SESSION_SELECT} WHERE s.id = $1", session_id))
