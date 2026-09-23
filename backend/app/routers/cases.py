"""Cases: listing, detail, status transitions, and penalty issuance.

Student reads are defended twice: the SQL restricts a student to their own
student_id, and the connection comes from deps.get_rls_db, whose GUCs make
the RLS policies on cases/penalties/appeals filter independently of the
query. Teachers see only cases from sessions they invigilate. HOD, Admin and
Exam Controller have pilot-wide oversight (a single-department pilot; see
README "Authorization model").
"""
from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.audit import ACTION_CASE_TRANSITION, ACTION_NOTICE_GENERATED, ACTION_PENALTY_ISSUED, record_audit
from app.deps import CurrentUser, get_client_ip, get_db, get_rls_db, require_any_role, require_role
from app.models import BehaviourType, CaseStatus, NoticeSource, NotificationType, PenaltyType, Role
from app.schemas import CaseDetailOut, CaseOut, CaseTransitionRequest, PenaltyOut, PenaltyRequest
from app.services.authorization import can_access_session
from app.services.case_views import fetch_case, list_cases, penalty_label
from app.services.case_workflow import TransitionNotAllowed, check_transition
from app.services.clock import local_date
from app.services.notices import NoticeFacts, generate_notice
from app.services.notifications import notify_role, notify_users

router = APIRouter(tags=["cases"])

CASE_COLUMNS = "id, session_id, seat_number, student_id, reference_no, status, created_at"
PENALTY_SELECT = """
    SELECT p.id, p.case_id, p.penalty_type, p.description, p.issued_by, u.full_name AS issued_by_name,
           p.notice_reference, p.notice_document, p.notice_source, p.revoked_at, p.created_at
    FROM penalties p JOIN users u ON u.id = p.issued_by
"""

require_case_reviewer = require_role(Role.TEACHER, Role.HOD)
require_hod = require_role(Role.HOD)
ERR_NOT_FOUND = "Case not found."


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


def row_to_penalty(row: asyncpg.Record) -> PenaltyOut:
    return PenaltyOut(
        id=str(row["id"]),
        case_id=str(row["case_id"]),
        penalty_type=PenaltyType(row["penalty_type"]),
        description=row["description"],
        issued_by=str(row["issued_by"]),
        issued_by_name=row["issued_by_name"],
        notice_reference=row["notice_reference"],
        notice_document=row["notice_document"],
        notice_source=NoticeSource(row["notice_source"]) if row["notice_source"] else None,
        revoked_at=row["revoked_at"],
        created_at=row["created_at"],
    )


@router.get("/api/cases", response_model=list[CaseDetailOut])
async def get_cases(
    case_status: CaseStatus | None = Query(default=None, alias="status"),
    behaviour_type: BehaviourType | None = None,
    student_id: UUID | None = None,
    course_code: str | None = Query(default=None, max_length=20),
    session_id: UUID | None = None,
    current_user: CurrentUser = Depends(require_any_role),
    conn: asyncpg.Connection = Depends(get_rls_db),
) -> list[CaseDetailOut]:
    return await list_cases(
        conn,
        role=current_user.role,
        user_id=current_user.user_id,
        status=case_status,
        behaviour_type=behaviour_type,
        student_id=str(student_id) if student_id else None,
        course_code=course_code,
        session_id=str(session_id) if session_id else None,
    )


@router.get("/api/cases/{case_id}", response_model=CaseDetailOut)
async def get_case(
    case_id: UUID,
    current_user: CurrentUser = Depends(require_any_role),
    conn: asyncpg.Connection = Depends(get_rls_db),
) -> CaseDetailOut:
    case = await fetch_case(conn, str(case_id), role=current_user.role, user_id=current_user.user_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
    return case


@router.post("/api/cases/{case_id}/transitions", response_model=CaseDetailOut)
async def transition_case(
    case_id: UUID,
    body: CaseTransitionRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_case_reviewer),
    conn: asyncpg.Connection = Depends(get_db),
) -> CaseDetailOut:
    async with conn.transaction():
        case = await conn.fetchrow(
            """
            SELECT c.status, c.reference_no, s.invigilator_id
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)

        current = CaseStatus(case["status"])
        try:
            check_transition(role=current_user.role, current=current, target=body.to_status)
        except TransitionNotAllowed as exc:
            code = status.HTTP_403_FORBIDDEN if exc.forbidden else status.HTTP_409_CONFLICT
            raise HTTPException(status_code=code, detail=exc.detail) from exc

        await conn.execute("UPDATE cases SET status = $1, updated_at = now() WHERE id = $2", body.to_status.value, case_id)
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_CASE_TRANSITION,
            target=str(case_id),
            new_value={"from": current.value, "to": body.to_status.value, "note": body.note},
            ip_address=get_client_ip(request),
        )
        if body.to_status == CaseStatus.ESCALATED:
            await notify_role(
                conn, Role.HOD, type_=NotificationType.CASE_UPDATE,
                title=f"Case {case['reference_no']} escalated",
                message="An invigilator escalated this case for your decision.",
                reference_type="case", reference_id=str(case_id),
            )
    updated = await fetch_case(conn, str(case_id), role=current_user.role, user_id=current_user.user_id)
    assert updated is not None
    return updated


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
            SELECT c.status, c.reference_no, c.student_id, c.teacher_note, s.course_code, s.room,
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
        if case["status"] != CaseStatus.CONFIRMED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A penalty can only follow a confirmed case.")
        if case["student_id"] is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This case has no identified student.")

        try:
            penalty_id = await conn.fetchval(
                """
                INSERT INTO penalties (case_id, penalty_type, description, issued_by, notice_reference)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
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
            new_value={"penalty_id": str(penalty_id), "penalty_type": body.penalty_type.value},
            ip_address=ip,
        )
        await notify_users(
            conn, [str(case["student_id"])], type_=NotificationType.PENALTY,
            title=f"Decision issued on case {case['reference_no']}",
            message=f"The Head of Department issued: {penalty_label(body.penalty_type.value)}. You may appeal from My Cases.",
            reference_type="case", reference_id=str(case_id),
        )

    # Generated after commit so the row lock isn't held across a slow API call;
    # the UNIQUE(case_id) insert above is what makes this run once per case.
    # generate_notice never raises: any failure falls back to the template.
    facts = NoticeFacts(
        notice_reference=case["reference_no"],
        student_name=case["student_name"],
        student_reg_no=case["student_reg_no"],
        course_code=case["course_code"],
        room=case["room"],
        exam_date=local_date(case["occurred_at"]).isoformat(),
        behaviours=[BehaviourType(b).value.replace("_", " ").title() for b in (case["behaviour_types"] or [])],
        penalty_type=penalty_label(body.penalty_type.value),
        penalty_description=body.description,
        issued_by=case["hod_name"],
        invigilator_observation=case["teacher_note"] or "",
    )
    document, source = await generate_notice(facts)
    async with conn.transaction():
        await conn.execute(
            "UPDATE penalties SET notice_document = $1, notice_source = $2 WHERE id = $3",
            document,
            source.value,
            penalty_id,
        )
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_NOTICE_GENERATED,
            target=str(case_id),
            new_value={"penalty_id": str(penalty_id), "source": source.value},
            ip_address=ip,
        )
    return row_to_penalty(await conn.fetchrow(f"{PENALTY_SELECT} WHERE p.id = $1", penalty_id))


@router.get("/api/cases/{case_id}/penalty", response_model=PenaltyOut)
async def get_penalty(
    case_id: UUID,
    current_user: CurrentUser = Depends(require_hod),
    conn: asyncpg.Connection = Depends(get_db),
) -> PenaltyOut:
    row = await conn.fetchrow(f"{PENALTY_SELECT} WHERE p.case_id = $1", case_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No penalty issued for this case.")
    return row_to_penalty(row)
