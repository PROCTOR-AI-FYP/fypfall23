"""Alerts: detections as the invigilator triages them.

Every detection already opened a pending_review case (routers/internal.py).
The invigilator's two triage decisions map onto that case:
  confirm  -> the case stays pending_review for the HOD, with the
              invigilator's note attached and the alert marked confirmed
  dismiss  -> the case moves pending_review -> dismissed through the normal
              state machine (a teacher may dismiss a pending case)
Alert status (new / reviewed / confirmed / dismissed) is derived: reviewed
once the invigilator has opened the evidence.
"""
from __future__ import annotations

import json
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import ACTION_ALERT_CONFIRMED, ACTION_CASE_TRANSITION, record_audit
from app.deps import CurrentUser, get_client_ip, get_db, require_role
from app.models import AlertStatus, BehaviourType, CaseStatus, NotificationType, Role
from app.schemas import AlertConfirmRequest, AlertDismissRequest, CaseDetailOut, DetectionOut
from app.services.authorization import can_review_evidence
from app.services.case_views import fetch_case
from app.services.case_workflow import TransitionNotAllowed, check_transition
from app.services.notifications import notify_role

router = APIRouter(prefix="/api/detections", tags=["alerts"])

require_alert_reader = require_role(Role.TEACHER, Role.HOD)
require_invigilator = require_role(Role.TEACHER)
ERR_NOT_FOUND = "Alert not found."

DETECTION_SELECT = """
    SELECT de.id, de.session_id, de.seat_number, de.behaviour_types, de.per_signal, de.composite_score,
           de.detected_at, de.reviewed_at, de.teacher_confirmed_at,
           c.id AS case_id, c.status AS case_status, c.student_id, c.reference_no,
           u.full_name AS student_name, s.invigilator_id
    FROM detection_events de
    JOIN exam_sessions s ON s.id = de.session_id
    LEFT JOIN cases c ON c.detection_event_id = de.id
    LEFT JOIN users u ON u.id = c.student_id
"""


def alert_status(row: asyncpg.Record) -> AlertStatus:
    if row["case_status"] == CaseStatus.DISMISSED.value:
        return AlertStatus.DISMISSED
    if row["teacher_confirmed_at"] is not None or row["case_status"] in (CaseStatus.CONFIRMED.value, CaseStatus.ESCALATED.value):
        return AlertStatus.CONFIRMED
    if row["reviewed_at"] is not None:
        return AlertStatus.REVIEWED
    return AlertStatus.NEW


def row_to_detection(row: asyncpg.Record) -> DetectionOut:
    per_signal = row["per_signal"]
    per_signal = json.loads(per_signal) if isinstance(per_signal, str) else per_signal
    return DetectionOut(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        case_id=str(row["case_id"]) if row["case_id"] else None,
        seat_number=row["seat_number"],
        student_id=str(row["student_id"]) if row["student_id"] else None,
        student_name=row["student_name"],
        behaviour_types=[BehaviourType(b) for b in row["behaviour_types"]],
        per_signal={BehaviourType(k): float(v) for k, v in per_signal.items()},
        composite_score=float(row["composite_score"]),
        detected_at=row["detected_at"],
        status=alert_status(row),
    )


@router.get("", response_model=list[DetectionOut])
async def list_detections(
    session_id: UUID | None = None,
    current_user: CurrentUser = Depends(require_alert_reader),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[DetectionOut]:
    """A teacher sees alerts from sessions they invigilate; the HOD sees all."""
    rows = await conn.fetch(
        f"""
        {DETECTION_SELECT}
        WHERE ($1::uuid IS NULL OR de.session_id = $1::uuid)
          AND ($2::uuid IS NULL OR s.invigilator_id = $2::uuid)
        ORDER BY de.detected_at DESC
        LIMIT 500
        """,
        str(session_id) if session_id else None,
        current_user.user_id if current_user.role == Role.TEACHER else None,
    )
    return [row_to_detection(row) for row in rows]


async def _locked_detection(conn: asyncpg.Connection, detection_id: UUID, current_user: CurrentUser) -> asyncpg.Record:
    row = await conn.fetchrow(f"{DETECTION_SELECT} WHERE de.id = $1 FOR UPDATE OF de", detection_id)
    invigilator_id = str(row["invigilator_id"]) if row is not None and row["invigilator_id"] else None
    if row is None or not can_review_evidence(role=current_user.role, user_id=current_user.user_id, invigilator_id=invigilator_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
    if row["case_id"] is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This alert has no case attached.")
    return row


@router.post("/{detection_id}/confirm", response_model=CaseDetailOut)
async def confirm_alert(
    detection_id: UUID,
    body: AlertConfirmRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_invigilator),
    conn: asyncpg.Connection = Depends(get_db),
) -> CaseDetailOut:
    note = (body.teacher_note or "").strip() or None
    async with conn.transaction():
        row = await _locked_detection(conn, detection_id, current_user)
        if row["case_status"] != CaseStatus.PENDING_REVIEW.value or row["teacher_confirmed_at"] is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This alert has already been triaged.")
        await conn.execute(
            "UPDATE detection_events SET teacher_confirmed_at = now(), teacher_confirmed_by = $2::uuid WHERE id = $1",
            detection_id,
            current_user.user_id,
        )
        await conn.execute(
            "UPDATE cases SET teacher_note = $2, teacher_note_by = $3::uuid, updated_at = now() WHERE id = $1",
            row["case_id"],
            note,
            current_user.user_id,
        )
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_ALERT_CONFIRMED,
            target=str(row["case_id"]),
            new_value={"detection_id": str(detection_id), "note": note},
            ip_address=get_client_ip(request),
        )
        await notify_role(
            conn, Role.HOD, type_=NotificationType.CASE_UPDATE,
            title=f"Case {row['reference_no']} awaiting review",
            message="An invigilator confirmed a live alert as a case.",
            reference_type="case", reference_id=str(row["case_id"]),
        )
    case = await fetch_case(conn, str(row["case_id"]), role=current_user.role, user_id=current_user.user_id)
    assert case is not None
    return case


@router.post("/{detection_id}/dismiss", response_model=DetectionOut)
async def dismiss_alert(
    detection_id: UUID,
    body: AlertDismissRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_invigilator),
    conn: asyncpg.Connection = Depends(get_db),
) -> DetectionOut:
    async with conn.transaction():
        row = await _locked_detection(conn, detection_id, current_user)
        current = CaseStatus(row["case_status"])
        try:
            check_transition(role=current_user.role, current=current, target=CaseStatus.DISMISSED)
        except TransitionNotAllowed as exc:
            code = status.HTTP_403_FORBIDDEN if exc.forbidden else status.HTTP_409_CONFLICT
            raise HTTPException(status_code=code, detail=exc.detail) from exc
        await conn.execute("UPDATE cases SET status = 'dismissed', updated_at = now() WHERE id = $1", row["case_id"])
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_CASE_TRANSITION,
            target=str(row["case_id"]),
            new_value={"from": current.value, "to": CaseStatus.DISMISSED.value, "note": (body.note or "").strip() or None,
                       "via": "alert_inbox"},
            ip_address=get_client_ip(request),
        )
    return row_to_detection(await conn.fetchrow(f"{DETECTION_SELECT} WHERE de.id = $1", detection_id))
