"""Admin-only account creation — the only path that can produce a staff
role, and the only path where role is a deliberate, explicit Admin choice.
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import ACTION_ADMIN_CREATE_USER, record_audit
from app.deps import CurrentUser, get_client_ip, get_db, require_admin
from app.models import Role
from app.schemas import AdminCreateUserRequest, UserOut
from app.security import hash_password, is_allowed_domain, is_student_shaped_local_part, local_part_of

router = APIRouter(prefix="/api/admin", tags=["admin"])

ERR_NON_UNIVERSITY_EMAIL = "Please use the university email domain."
ERR_STUDENT_ROLE_NON_NUMERIC = "role=student requires a six-digit registration-number email."
ERR_STAFF_ROLE_NUMERIC = "Staff roles cannot use a six-digit (student-shaped) email."


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def admin_create_user(
    body: AdminCreateUserRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_db),
) -> UserOut:
    if not is_allowed_domain(body.email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERR_NON_UNIVERSITY_EMAIL)

    local_part = local_part_of(body.email)
    student_shaped = is_student_shaped_local_part(local_part)

    if body.role == Role.STUDENT and not student_shaped:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERR_STUDENT_ROLE_NON_NUMERIC)
    if body.role != Role.STUDENT and student_shaped:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERR_STAFF_ROLE_NUMERIC)

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO users (full_name, email, password_hash, role, registration_or_employee_no, status, email_verified)
            VALUES ($1, $2, $3, $4, $5, 'active', true)
            RETURNING id, full_name, email, role, registration_or_employee_no, status, email_verified, created_at
            """,
            body.full_name,
            body.email,
            hash_password(body.password_or_send_setup_email),
            body.role.value,
            local_part,
        )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or registration/employee number already in use.") from exc

    await record_audit(
        conn,
        actor_id=current_user.user_id,
        action=ACTION_ADMIN_CREATE_USER,
        target=body.email,
        new_value={"role": body.role.value},
        ip_address=get_client_ip(request),
    )

    return UserOut(
        id=str(row["id"]),
        full_name=row["full_name"],
        email=row["email"],
        role=Role(row["role"]),
        registration_or_employee_no=row["registration_or_employee_no"],
        status=row["status"],
        email_verified=row["email_verified"],
        created_at=row["created_at"],
    )
