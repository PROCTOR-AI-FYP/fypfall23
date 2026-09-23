"""Endpoints for the AI detection worker (service-to-service, API-key auth).

POST /internal/frames      per-frame signal scores -> buffers -> triggered seats
POST /internal/detections  a confirmed alert with its snapshot -> case, live
                           Socket.IO event, and MQTT alert to the room device
"""
from __future__ import annotations

import json
import re

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from app.audit import ACTION_DETECTION_RECORDED, record_audit
from app.config import settings
from app.deps import get_db, require_internal_api_key
from app.models import AlertStatus, BehaviourType, NotificationType
from app.routers.cases import CASE_COLUMNS, row_to_case
from app.schemas import CaseOut, DetectionEventIn, FrameRequest, FrameResponse, TriggeredSeatOut
from app.services.detection import SeatSignals, get_detection_config, process_frame
from app.services.exam_sessions import SessionMeta, get_session_meta
from app.services.mqtt import alert_topic, mqtt_service
from app.services.notifications import notify_users
from app.sockets import emit_detection

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_api_key)])

SNAPSHOT_FILENAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}\.(?:jpg|jpeg|png)$")


async def _require_active_session(conn: asyncpg.Connection, session_id: str) -> SessionMeta:
    meta = await get_session_meta(conn, session_id)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam session not found.")
    if not meta.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Exam session is not in progress.")
    return meta


def format_reference_no(course_code: str, year: int, sequence: int) -> str:
    department = "".join(ch for ch in course_code if ch.isalpha())[:2].upper() or "CS"
    return f"AU-{department}-INT-{year}-{sequence:03d}"


@router.post("/frames", response_model=FrameResponse)
async def ingest_frame(body: FrameRequest, conn: asyncpg.Connection = Depends(get_db)) -> FrameResponse:
    session_id = str(body.session_id)
    meta = await _require_active_session(conn, session_id)

    seats = [
        SeatSignals(
            seat_number=seat.seat_number,
            signals={
                signal: score
                for signal, score in seat.signals.items()
                if meta.silent_mode or signal != BehaviourType.LIP_MOVEMENT
            },
        )
        for seat in body.seats
    ]
    triggered = await process_frame(session_id, body.frame_index, seats, await get_detection_config(conn))
    return FrameResponse(
        triggered=[
            TriggeredSeatOut(
                seat_number=seat.seat_number,
                behaviour_types=seat.behaviour_types,
                per_signal=seat.per_signal,
                composite_score=seat.composite_score,
            )
            for seat in triggered
        ]
    )


@router.post("/detections", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def record_detection(body: DetectionEventIn, conn: asyncpg.Connection = Depends(get_db)) -> CaseOut:
    session_id = str(body.session_id)
    meta = await _require_active_session(conn, session_id)

    # The purge job deletes whatever path is stored here, so it must stay
    # inside this session's folder of the snapshot bucket.
    expected_prefix = f"{settings.supabase_snapshot_bucket}/{session_id}/"
    filename = body.snapshot_path.removeprefix(expected_prefix)
    if not body.snapshot_path.startswith(expected_prefix) or not SNAPSHOT_FILENAME_RE.match(filename):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"snapshot_path must be {expected_prefix}<name>.jpg|jpeg|png",
        )
    if set(body.per_signal) != set(body.behaviour_types):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="per_signal must have exactly one score per behaviour type.",
        )

    behaviour_values = [b.value for b in body.behaviour_types]
    per_signal = {signal.value: score for signal, score in body.per_signal.items()}
    async with conn.transaction():
        try:
            async with conn.transaction():
                detection_id = await conn.fetchval(
                    """
                    INSERT INTO detection_events
                        (session_id, seat_number, behaviour_types, per_signal, composite_score, snapshot_path, detected_at)
                    VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                    RETURNING id
                    """,
                    session_id,
                    body.seat_number,
                    behaviour_values,
                    json.dumps(per_signal),
                    body.composite_score,
                    body.snapshot_path,
                    body.detected_at,
                )
        except asyncpg.UniqueViolationError as exc:
            # Same snapshot = same detection: a retried POST, not a new incident.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="This detection (snapshot) has already been recorded."
            ) from exc
        student = await conn.fetchrow(
            """
            SELECT sa.student_id, u.full_name
            FROM seat_assignments sa LEFT JOIN users u ON u.id = sa.student_id
            WHERE sa.session_id = $1 AND sa.seat_number = $2
            """,
            session_id,
            body.seat_number,
        )
        student_id = student["student_id"] if student is not None else None
        student_name = student["full_name"] if student is not None else None
        sequence = await conn.fetchval("SELECT nextval('case_reference_seq')")
        case_row = await conn.fetchrow(
            f"""
            INSERT INTO cases (session_id, seat_number, student_id, reference_no, status, detection_event_id)
            VALUES ($1, $2, $3, $4, 'pending_review', $5)
            RETURNING {CASE_COLUMNS}
            """,
            session_id,
            body.seat_number,
            student_id,
            format_reference_no(meta.course_code, body.detected_at.year, sequence),
            detection_id,
        )
        await record_audit(
            conn,
            actor_id=None,
            action=ACTION_DETECTION_RECORDED,
            target=str(case_row["id"]),
            new_value={"detection_event_id": str(detection_id), "seat_number": body.seat_number},
            ip_address=None,
        )
        if meta.invigilator_id:
            labels = ", ".join(b.value.replace("_", " ").title() for b in body.behaviour_types)
            await notify_users(
                conn, [meta.invigilator_id], type_=NotificationType.ALERT,
                title=f"Alert at seat {body.seat_number}",
                message=f"{labels} ({meta.course_code}, {meta.room})",
                reference_type="session", reference_id=session_id,
            )

    case = row_to_case(case_row)
    detected_at = body.detected_at.isoformat()
    # Same fields as GET /api/detections returns, so the UI handles both alike.
    await emit_detection(
        session_id,
        meta.invigilator_id,
        {
            "id": str(detection_id),
            "case_id": case.id,
            "reference_no": case.reference_no,
            "session_id": session_id,
            "seat_number": body.seat_number,
            "student_id": case.student_id,
            "student_name": student_name,
            "behaviour_types": behaviour_values,
            "per_signal": per_signal,
            "composite_score": body.composite_score,
            "detected_at": detected_at,
            "status": AlertStatus.NEW.value,
        },
    )
    # Devices get no student identity, only what an in-room indicator needs.
    await mqtt_service.publish(
        alert_topic(meta.room),
        {
            "reference_no": case.reference_no,
            "seat_number": body.seat_number,
            "behaviour_types": behaviour_values,
            "detected_at": detected_at,
        },
    )
    return case
