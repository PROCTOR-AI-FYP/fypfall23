"""Case listing, status transitions, and penalty issuance.

GET /api/cases is deliberately defended twice for students:
  1. Application-level filter: the SQL WHERE clause restricts a student to
     their own student_id.
  2. Database-level: the connection comes from deps.get_rls_db, which sets
     the `app.current_user_id` / `app.current_role` GUCs from the JWT for
     this transaction (see app/db.py). The `cases_student_isolation` RLS
     policy in db/schema.sql filters independently of the query, so even a
     bug here cannot leak another student's case.
Teachers see only cases from sessions they invigilate.
"""
from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import ACTION_CASE_TRANSITION, ACTION_NOTICE_GENERATED, ACTION_PENALTY_ISSUED, record_audit
from app.deps import CurrentUser, get_client_ip, get_current_user, get_db, get_rls_db, require_role
from app.models import BehaviourType, CaseStatus, NoticeSource, PenaltyType, Role
from app.schemas import CaseOut, CaseTransitionRequest, PenaltyOut, PenaltyRequest
from app.services.authorization import can_access_session
from app.services.case_workflow import TransitionNotAllowed, check_transition
from app.services.notices import NoticeFacts, generate_notice

router = APIRouter(tags=["cases"])

CASE_COLUMNS = "id, session_id, seat_number, student_id, reference_no, status, created_at"
CASE_COLUMNS_ALIASED = "c.id, c.session_id, c.seat_number, c.student_id, c.reference_no, c.status, c.created_at"
PENALTY_COLUMNS = (
    "id, case_id, penalty_type, description, notice_reference, notice_document, notice_source, created_at"
)

require_case_reviewer = require_role(Role.TEACHER, Role.HOD)
require_hod = require_role(Role.HOD)


def row_to_case(row: asyncpg.Record) -> CaseOut:
    return CaseOut(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        seat_number=row["seat_number"],
        student_id=str(row["student_id"]) if row["student_id"] is not None else None,
        reference_no=row["reference_no"],
        status=CaseStatus(row["status"]),
        created_at=row["created_at"],
    )


def _row_to_penalty(row: asyncpg.Record) -> PenaltyOut:
    return PenaltyOut(
        id=str(row["id"]),
        case_id=str(row["case_id"]),
        penalty_type=PenaltyType(row["penalty_type"]),
        description=row["description"],
        notice_reference=row["notice_reference"],
        notice_document=row["notice_document"],
        notice_source=NoticeSource(row["notice_source"]) if row["notice_source"] else None,
        created_at=row["created_at"],
    )


@router.get("/api/cases", response_model=list[CaseOut])
async def list_cases(
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_rls_db),
) -> list[CaseOut]:
    if current_user.role == Role.STUDENT:
        rows = await conn.fetch(
            f"SELECT {CASE_COLUMNS} FROM cases WHERE student_id = $1 ORDER BY created_at DESC",
            current_user.user_id,
        )
    elif current_user.role == Role.TEACHER:
        rows = await conn.fetch(
            f"""
            SELECT {CASE_COLUMNS_ALIASED}
            FROM cases c JOIN exam_sessions s ON s.id = c.session_id
            WHERE s.invigilator_id = $1
            ORDER BY c.created_at DESC
            """,
            current_user.user_id,
        )
    else:
        rows = await conn.fetch(f"SELECT {CASE_COLUMNS} FROM cases ORDER BY created_at DESC")
    return [row_to_case(row) for row in rows]


@router.post("/api/cases/{case_id}/transitions", response_model=CaseOut)
async def transition_case(
    case_id: UUID,
    body: CaseTransitionRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_case_reviewer),
    conn: asyncpg.Connection = Depends(get_db),
) -> CaseOut:
    async with conn.transaction():
        case = await conn.fetchrow(
            """
            SELECT c.status, s.invigilator_id
            FROM cases c JOIN exam_sessions s ON s.id = c.session_id
            WHERE c.id = $1
            FOR UPDATE OF c
            """,
            case_id,
        )
        invigilator_id = str(case["invigilator_id"]) if case and case["invigilator_id"] else None
        if case is None or not can_access_session(
            role=current_user.role, user_id=current_user.user_id, invigilator_id=invigilator_id
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")

        current = CaseStatus(case["status"])
        try:
            check_transition(role=current_user.role, current=current, target=body.to_status)
        except TransitionNotAllowed as exc:
            code = status.HTTP_403_FORBIDDEN if exc.forbidden else status.HTTP_409_CONFLICT
            raise HTTPException(status_code=code, detail=exc.detail) from exc

        row = await conn.fetchrow(
            f"UPDATE cases SET status = $1, updated_at = now() WHERE id = $2 RETURNING {CASE_COLUMNS}",
            body.to_status.value,
            case_id,
        )
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_CASE_TRANSITION,
            target=str(case_id),
            new_value={"from": current.value, "to": body.to_status.value, "note": body.note},
            ip_address=get_client_ip(request),
        )
    return row_to_case(row)


@router.post("/api/cases/{case_id}/penalty", response_model=PenaltyOut, status_code=status.HTTP_201_CREATED)
async def issue_penalty(
    case_id: UUID,
    body: PenaltyRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_hod),
    conn: asyncpg.Connection = Depends(get_db),
) -> PenaltyOut:
    ip = get_client_ip(request)
    async with conn.transaction():
        case = await conn.fetchrow(
            """
            SELECT c.status, c.reference_no, c.student_id, s.course_code, s.room,
                   u.full_name AS student_name, u.registration_or_employee_no AS student_reg_no,
                   de.behaviour_types, COALESCE(de.detected_at, c.created_at) AS occurred_at,
                   hod.full_name AS hod_name
            FROM cases c
            JOIN exam_sessions s ON s.id = c.session_id
            LEFT JOIN users u ON u.id = c.student_id
            LEFT JOIN detection_events de ON de.id = c.detection_event_id
            JOIN users hod ON hod.id = $2
            WHERE c.id = $1
            FOR UPDATE OF c
            """,
            case_id,
            current_user.user_id,
        )
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")
        if case["status"] != CaseStatus.CONFIRMED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A penalty can only follow a confirmed case.")
        if case["student_id"] is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This case has no identified student.")

        try:
            penalty = await conn.fetchrow(
                f"""
                INSERT INTO penalties (case_id, penalty_type, description, issued_by, notice_reference)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING {PENALTY_COLUMNS}
                """,
                case_id,
                body.penalty_type.value,
                body.description,
                current_user.user_id,
                case["reference_no"],
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="A penalty has already been issued for this case."
            ) from exc
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_PENALTY_ISSUED,
            target=str(case_id),
            new_value={"penalty_id": str(penalty["id"]), "penalty_type": body.penalty_type.value},
            ip_address=ip,
        )

    # Generated after commit so the row lock isn't held across a slow API call;
    # the UNIQUE(case_id) insert above is what makes this run once per case.
    facts = NoticeFacts(
        notice_reference=case["reference_no"],
        student_name=case["student_name"],
        student_reg_no=case["student_reg_no"],
        course_code=case["course_code"],
        room=case["room"],
        exam_date=case["occurred_at"].date().isoformat(),
        behaviours=[BehaviourType(b).value.replace("_", " ").title() for b in (case["behaviour_types"] or [])],
        penalty_type=body.penalty_type.value.replace("_", " ").title(),
        penalty_description=body.description,
        issued_by=case["hod_name"],
    )
    document, source = await generate_notice(facts)
    async with conn.transaction():
        penalty = await conn.fetchrow(
            f"UPDATE penalties SET notice_document = $1, notice_source = $2 WHERE id = $3 RETURNING {PENALTY_COLUMNS}",
            document,
            source.value,
            penalty["id"],
        )
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_NOTICE_GENERATED,
            target=str(penalty["id"]),
            new_value={"source": source.value},
            ip_address=ip,
        )
    return _row_to_penalty(penalty)


@router.get("/api/cases/{case_id}/penalty", response_model=PenaltyOut)
async def get_penalty(
    case_id: UUID,
    current_user: CurrentUser = Depends(require_hod),
    conn: asyncpg.Connection = Depends(get_db),
) -> PenaltyOut:
    row = await conn.fetchrow(f"SELECT {PENALTY_COLUMNS} FROM penalties WHERE case_id = $1", case_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No penalty issued for this case.")
    return _row_to_penalty(row)
