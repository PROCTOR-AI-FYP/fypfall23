"""Appeals: a student appeals an issued penalty; the HOD resolves it.

Rules:
  - only the accused student, only against a confirmed case with a live
    (unrevoked) penalty, within APPEAL_WINDOW_DAYS of the penalty
  - at most one open appeal per case (unique partial index in schema.sql),
    and the HOD's decision is final: no second appeal after resolution
  - accepting dismisses the case through case_workflow.check_appeal_exit and
    revokes the penalty; rejecting leaves both as they are
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.audit import ACTION_APPEAL_RESOLVED, ACTION_APPEAL_SUBMITTED, ACTION_CASE_TRANSITION, record_audit
from app.config import settings
from app.deps import CurrentUser, get_client_ip, get_db, get_rls_db, require_role
from app.models import AppealStatus, CaseStatus, NotificationType, Role
from app.schemas import AppealCreate, AppealOut, AppealResolve
from app.services.case_views import APPEAL_SELECT, row_to_appeal
from app.services.case_workflow import TransitionNotAllowed, check_appeal_exit
from app.services.notifications import notify_role, notify_users

router = APIRouter(tags=["appeals"])

require_student = require_role(Role.STUDENT)
require_hod = require_role(Role.HOD)
require_appeal_reader = require_role(Role.HOD, Role.STUDENT)
ERR_NOT_FOUND = "Appeal not found."


@router.post("/api/cases/{case_id}/appeals", response_model=AppealOut, status_code=status.HTTP_201_CREATED)
async def file_appeal(
    case_id: UUID,
    body: AppealCreate,
    request: Request,
    current_user: CurrentUser = Depends(require_student),
    conn: asyncpg.Connection = Depends(get_rls_db),
) -> AppealOut:
    statement = body.statement.strip()
    if not statement:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The appeal statement is empty.")

    # get_rls_db already holds a transaction; RLS hides other students' cases entirely.
    case = await conn.fetchrow(
        """
        SELECT c.status, c.reference_no, c.student_id, p.created_at AS penalty_at, p.revoked_at
        FROM cases c LEFT JOIN penalties p ON p.case_id = c.id
        WHERE c.id = $1 AND c.student_id = $2::uuid
        FOR UPDATE OF c
        """,
        case_id,
        current_user.user_id,
    )
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")
    if case["status"] != CaseStatus.CONFIRMED.value or case["penalty_at"] is None or case["revoked_at"] is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only an issued penalty on a confirmed case can be appealed.")
    if datetime.now(timezone.utc) > case["penalty_at"] + timedelta(days=settings.appeal_window_days):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The {settings.appeal_window_days}-day appeal window for this case has closed.",
        )
    if await conn.fetchval("SELECT 1 FROM appeals WHERE case_id = $1 AND status <> 'open'", case_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This case's appeal has already been decided; the decision is final.")

    try:
        async with conn.transaction():  # savepoint, so a duplicate leaves the outer transaction usable
            appeal_id = await conn.fetchval(
                """
                INSERT INTO appeals (case_id, student_id, statement, supporting_info)
                VALUES ($1, $2::uuid, $3, $4)
                RETURNING id
                """,
                case_id,
                current_user.user_id,
                statement,
                (body.supporting_info or "").strip() or None,
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An appeal for this case is already open.") from exc

    await record_audit(
        conn,
        actor_id=current_user.user_id,
        action=ACTION_APPEAL_SUBMITTED,
        target=str(case_id),
        new_value={"appeal_id": str(appeal_id)},
        ip_address=get_client_ip(request),
    )
    await notify_role(
        conn, Role.HOD, type_=NotificationType.APPEAL,
        title=f"Appeal filed on case {case['reference_no']}",
        message="A student has appealed a penalty and is waiting for your decision.",
        reference_type="appeal", reference_id=str(appeal_id),
    )
    return row_to_appeal(await conn.fetchrow(f"{APPEAL_SELECT} WHERE a.id = $1", appeal_id))


@router.get("/api/appeals", response_model=list[AppealOut])
async def list_appeals(
    appeal_status: AppealStatus | None = Query(default=None, alias="status"),
    current_user: CurrentUser = Depends(require_appeal_reader),
    conn: asyncpg.Connection = Depends(get_rls_db),
) -> list[AppealOut]:
    rows = await conn.fetch(
        f"""
        {APPEAL_SELECT}
        WHERE ($1::text IS NULL OR a.status = $1)
          AND ($2::uuid IS NULL OR a.student_id = $2::uuid)
        ORDER BY (a.status = 'open') DESC, a.submitted_at DESC
        """,
        appeal_status.value if appeal_status else None,
        current_user.user_id if current_user.role == Role.STUDENT else None,
    )
    return [row_to_appeal(row) for row in rows]


@router.get("/api/appeals/{appeal_id}", response_model=AppealOut)
async def get_appeal(
    appeal_id: UUID,
    current_user: CurrentUser = Depends(require_appeal_reader),
    conn: asyncpg.Connection = Depends(get_rls_db),
) -> AppealOut:
    row = await conn.fetchrow(f"{APPEAL_SELECT} WHERE a.id = $1", appeal_id)
    if row is None or (current_user.role == Role.STUDENT and str(row["student_id"]) != current_user.user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
    return row_to_appeal(row)


@router.post("/api/appeals/{appeal_id}/resolve", response_model=AppealOut)
async def resolve_appeal(
    appeal_id: UUID,
    body: AppealResolve,
    request: Request,
    current_user: CurrentUser = Depends(require_hod),
    conn: asyncpg.Connection = Depends(get_db),
) -> AppealOut:
    if body.status == AppealStatus.OPEN:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Resolve an appeal as accepted or rejected.")
    review_note = body.review_note.strip()
    if not review_note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Give your reasoning for the decision.")
    ip = get_client_ip(request)

    async with conn.transaction():
        appeal = await conn.fetchrow(
            """
            SELECT a.status, a.case_id, a.student_id, c.status AS case_status, c.reference_no
            FROM appeals a JOIN cases c ON c.id = a.case_id
            WHERE a.id = $1
            FOR UPDATE OF a, c
            """,
            appeal_id,
        )
        if appeal is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
        if appeal["status"] != AppealStatus.OPEN.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This appeal has already been resolved.")

        case_id = appeal["case_id"]
        if body.status == AppealStatus.ACCEPTED:
            try:
                check_appeal_exit(role=current_user.role, current=CaseStatus(appeal["case_status"]))
            except TransitionNotAllowed as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail) from exc
            await conn.execute("UPDATE cases SET status = 'dismissed', updated_at = now() WHERE id = $1", case_id)
            await conn.execute(
                "UPDATE penalties SET revoked_at = now(), revoked_by = $2::uuid WHERE case_id = $1", case_id, current_user.user_id
            )
            await record_audit(
                conn,
                actor_id=current_user.user_id,
                action=ACTION_CASE_TRANSITION,
                target=str(case_id),
                new_value={"from": CaseStatus.CONFIRMED.value, "to": CaseStatus.DISMISSED.value, "via": "appeal",
                           "appeal_id": str(appeal_id)},
                ip_address=ip,
            )

        await conn.execute(
            """
            UPDATE appeals SET status = $2, review_note = $3, reviewed_by = $4::uuid, resolved_at = now()
            WHERE id = $1
            """,
            appeal_id,
            body.status.value,
            review_note,
            current_user.user_id,
        )
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_APPEAL_RESOLVED,
            target=str(case_id),
            new_value={"appeal_id": str(appeal_id), "decision": body.status.value, "note": review_note},
            ip_address=ip,
        )
        await notify_users(
            conn, [str(appeal["student_id"])], type_=NotificationType.APPEAL,
            title=f"Appeal {body.status.value} on case {appeal['reference_no']}",
            message=(
                "Your appeal was accepted; the case is dismissed and the penalty withdrawn."
                if body.status == AppealStatus.ACCEPTED
                else "Your appeal was rejected. The Head of Department's reasoning is on the case page."
            ),
            reference_type="case", reference_id=str(case_id),
        )
    return row_to_appeal(await conn.fetchrow(f"{APPEAL_SELECT} WHERE a.id = $1", appeal_id))
