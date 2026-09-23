"""Read models for cases and appeals, shared by the case, appeal and alert routes.

A case's timeline is read straight from audit_log (append-only), so what the
HOD sees as the case history is exactly the evidentiary record.

Students get a narrower view of their own case: no invigilator note, no
internal timeline, no staff identities beyond who issued a penalty.
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

from app.audit import (
    ACTION_ALERT_CONFIRMED,
    ACTION_APPEAL_RESOLVED,
    ACTION_APPEAL_SUBMITTED,
    ACTION_CASE_TRANSITION,
    ACTION_CLIP_STORED,
    ACTION_DETECTION_RECORDED,
    ACTION_NOTICE_GENERATED,
    ACTION_PENALTY_ISSUED,
)
from app.models import AppealStatus, BehaviourType, CaseStatus, PenaltyType, Role
from app.schemas import AppealOut, CaseDetailOut, PenaltySummaryOut, TimelineEntryOut

CASE_SELECT = """
    SELECT c.id, c.reference_no, c.session_id, c.student_id, c.seat_number, c.status, c.detection_event_id,
           c.teacher_note, c.created_at, c.updated_at,
           stu.full_name AS student_name, stu.registration_or_employee_no AS student_reg_no,
           s.course_code, s.course_name, s.room AS classroom_name, s.invigilator_id,
           COALESCE(note_author.full_name, inv.full_name) AS teacher_name,
           COALESCE(de.behaviour_types, ARRAY[]::text[]) AS behaviour_types,
           COALESCE(de.composite_score, 0) AS composite_score,
           p.id AS penalty_id, p.penalty_type, p.description AS penalty_description, p.issued_by,
           issuer.full_name AS issued_by_name, p.notice_reference, p.revoked_at, p.created_at AS penalty_created_at,
           a.id AS appeal_id, a.student_id AS appeal_student_id, a.statement, a.supporting_info,
           a.status AS appeal_status, a.reviewed_by, reviewer.full_name AS reviewer_name, a.review_note,
           a.submitted_at, a.resolved_at
    FROM cases c
    JOIN exam_sessions s ON s.id = c.session_id
    LEFT JOIN users stu ON stu.id = c.student_id
    LEFT JOIN users inv ON inv.id = s.invigilator_id
    LEFT JOIN users note_author ON note_author.id = c.teacher_note_by
    LEFT JOIN detection_events de ON de.id = c.detection_event_id
    LEFT JOIN penalties p ON p.case_id = c.id
    LEFT JOIN users issuer ON issuer.id = p.issued_by
    LEFT JOIN LATERAL (
        SELECT * FROM appeals ap WHERE ap.case_id = c.id ORDER BY ap.submitted_at DESC LIMIT 1
    ) a ON true
    LEFT JOIN users reviewer ON reviewer.id = a.reviewed_by
"""

APPEAL_SELECT = """
    SELECT a.id, a.case_id, a.student_id, a.statement, a.supporting_info, a.status, a.reviewed_by,
           a.review_note, a.submitted_at, a.resolved_at,
           c.reference_no, stu.full_name AS student_name, stu.registration_or_employee_no AS student_reg_no,
           reviewer.full_name AS reviewer_name
    FROM appeals a
    JOIN cases c ON c.id = a.case_id
    JOIN users stu ON stu.id = a.student_id
    LEFT JOIN users reviewer ON reviewer.id = a.reviewed_by
"""

TIMELINE_ACTIONS = [
    ACTION_DETECTION_RECORDED, ACTION_CLIP_STORED, ACTION_ALERT_CONFIRMED, ACTION_CASE_TRANSITION,
    ACTION_PENALTY_ISSUED, ACTION_NOTICE_GENERATED, ACTION_APPEAL_SUBMITTED, ACTION_APPEAL_RESOLVED,
]
SYSTEM_ACTOR = "ProctorAI system"
STATUS_TITLES = {
    CaseStatus.CONFIRMED.value: "Case confirmed",
    CaseStatus.DISMISSED.value: "Case dismissed",
    CaseStatus.ESCALATED.value: "Case escalated",
    CaseStatus.PENDING_REVIEW.value: "Case reopened",
}


def penalty_label(value: str) -> str:
    return PenaltyType(value).value.replace("_", " ").title()


def row_to_appeal(row: asyncpg.Record) -> AppealOut:
    return AppealOut(
        id=str(row["id"]),
        case_id=str(row["case_id"]),
        case_reference_no=row["reference_no"],
        student_id=str(row["student_id"]),
        student_name=row["student_name"],
        student_reg_no=row["student_reg_no"],
        statement=row["statement"],
        supporting_info=row["supporting_info"],
        status=AppealStatus(row["status"]),
        reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] else None,
        reviewer_name=row["reviewer_name"],
        review_note=row["review_note"],
        submitted_at=row["submitted_at"],
        resolved_at=row["resolved_at"],
    )


def _case_from_row(row: asyncpg.Record, *, student_view: bool) -> CaseDetailOut:
    penalty = None
    if row["penalty_id"] is not None:
        penalty = PenaltySummaryOut(
            id=str(row["penalty_id"]),
            case_id=str(row["id"]),
            penalty_type=PenaltyType(row["penalty_type"]),
            description=row["penalty_description"],
            issued_by=str(row["issued_by"]),
            issued_by_name=row["issued_by_name"] or "",
            notice_reference=row["notice_reference"],
            revoked_at=row["revoked_at"],
            created_at=row["penalty_created_at"],
        )
    appeal = None
    if row["appeal_id"] is not None:
        appeal = AppealOut(
            id=str(row["appeal_id"]),
            case_id=str(row["id"]),
            case_reference_no=row["reference_no"],
            student_id=str(row["appeal_student_id"]),
            student_name=row["student_name"] or "",
            student_reg_no=row["student_reg_no"] or "",
            statement=row["statement"],
            supporting_info=row["supporting_info"],
            status=AppealStatus(row["appeal_status"]),
            reviewed_by=None if student_view or not row["reviewed_by"] else str(row["reviewed_by"]),
            reviewer_name=None if student_view else row["reviewer_name"],
            review_note=row["review_note"],
            submitted_at=row["submitted_at"],
            resolved_at=row["resolved_at"],
        )
    return CaseDetailOut(
        id=str(row["id"]),
        reference_no=row["reference_no"],
        session_id=str(row["session_id"]),
        student_id=str(row["student_id"]) if row["student_id"] else None,
        student_name=row["student_name"],
        student_reg_no=row["student_reg_no"],
        course_code=row["course_code"],
        course_name=row["course_name"],
        classroom_name=row["classroom_name"],
        seat_number=row["seat_number"],
        behaviour_types=[BehaviourType(b) for b in row["behaviour_types"]],
        composite_score=float(row["composite_score"]),
        status=CaseStatus(row["status"]),
        detection_event_id=str(row["detection_event_id"]) if row["detection_event_id"] else None,
        teacher_note=None if student_view else row["teacher_note"],
        teacher_id=None if student_view or not row["invigilator_id"] else str(row["invigilator_id"]),
        teacher_name=None if student_view else row["teacher_name"],
        penalty=penalty,
        appeal=appeal,
        timeline=[],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _timeline_entry(row: asyncpg.Record) -> TimelineEntryOut:
    action, value = row["action"], _json(row["new_value"])
    title: str
    details: str | None = None
    if action == ACTION_DETECTION_RECORDED:
        title, details = "Detection recorded", f"Seat {value.get('seat_number')} flagged by the proctoring system"
    elif action == ACTION_CLIP_STORED:
        title = "Evidence clip stored"
    elif action == ACTION_ALERT_CONFIRMED:
        title, details = "Confirmed as case by invigilator", value.get("note") or None
    elif action == ACTION_CASE_TRANSITION:
        to_status = value.get("to", "")
        title = "Case dismissed on appeal" if value.get("via") == "appeal" else STATUS_TITLES.get(to_status, "Status changed")
        details = value.get("note") or None
    elif action == ACTION_PENALTY_ISSUED:
        title = f"Penalty issued: {penalty_label(value['penalty_type'])}" if value.get("penalty_type") else "Penalty issued"
    elif action == ACTION_NOTICE_GENERATED:
        title = "Notice generated"
        details = (
            "Drafted with Claude and checked against the case record"
            if value.get("source") == "anthropic"
            else "Rendered from the standard notice template"
        )
    elif action == ACTION_APPEAL_SUBMITTED:
        title, details = "Appeal submitted", "Student submitted an appeal"
    else:  # ACTION_APPEAL_RESOLVED
        title, details = f"Appeal {value.get('decision', 'resolved')}", value.get("note") or None
    return TimelineEntryOut(
        id=str(row["id"]),
        action=title,
        actor_name=row["actor_name"] or SYSTEM_ACTOR,
        actor_role=Role(row["actor_role"]) if row["actor_role"] else None,
        details=details,
        timestamp=row["created_at"],
    )


def _json(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value or {})


async def fetch_timeline(conn: asyncpg.Connection, case_id: str) -> list[TimelineEntryOut]:
    rows = await conn.fetch(
        """
        SELECT al.id, al.action, al.new_value, al.created_at, u.full_name AS actor_name, u.role AS actor_role
        FROM audit_log al LEFT JOIN users u ON u.id = al.actor_id
        WHERE al.target = $1 AND al.action = ANY($2::text[])
        ORDER BY al.created_at, al.id
        """,
        case_id,
        TIMELINE_ACTIONS,
    )
    return [_timeline_entry(row) for row in rows]


async def fetch_case(
    conn: asyncpg.Connection, case_id: str, *, role: Role, user_id: str, with_timeline: bool = True
) -> CaseDetailOut | None:
    """One case as `role` may see it, or None if it doesn't exist or isn't theirs.

    Scoping mirrors list_cases: students their own (RLS enforces this too when
    `conn` comes from get_rls_db), teachers the sessions they invigilate.
    """
    row = await conn.fetchrow(f"{CASE_SELECT} WHERE c.id = $1::uuid", case_id)
    if row is None:
        return None
    if role == Role.STUDENT and str(row["student_id"]) != user_id:
        return None
    if role == Role.TEACHER and str(row["invigilator_id"]) != user_id:
        return None
    case = _case_from_row(row, student_view=role == Role.STUDENT)
    if with_timeline and role != Role.STUDENT:
        case.timeline = await fetch_timeline(conn, case.id)
    return case


async def list_cases(
    conn: asyncpg.Connection,
    *,
    role: Role,
    user_id: str,
    status: CaseStatus | None = None,
    behaviour_type: BehaviourType | None = None,
    student_id: str | None = None,
    course_code: str | None = None,
    session_id: str | None = None,
) -> list[CaseDetailOut]:
    conditions: list[str] = []
    params: list[Any] = []

    def where(sql: str, value: Any) -> None:
        params.append(value)
        conditions.append(sql.format(f"${len(params)}"))

    if role == Role.STUDENT:
        where("c.student_id = {}::uuid", user_id)
    elif role == Role.TEACHER:
        where("s.invigilator_id = {}::uuid", user_id)
    if status is not None:
        where("c.status = {}", status.value)
    if behaviour_type is not None:
        where("{} = ANY(de.behaviour_types)", behaviour_type.value)
    if student_id is not None:
        where("c.student_id = {}::uuid", student_id)
    if course_code:
        where("s.course_code = {}", course_code)
    if session_id is not None:
        where("c.session_id = {}::uuid", session_id)

    # Only $n placeholders are interpolated; every value is a bind parameter.
    clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await conn.fetch(f"{CASE_SELECT} {clause} ORDER BY c.created_at DESC", *params)
    return [_case_from_row(row, student_view=role == Role.STUDENT) for row in rows]
