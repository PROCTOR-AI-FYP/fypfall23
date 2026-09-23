"""User management. Admin creation is the only path that can produce a staff
role, and role is always a deliberate, explicit Admin choice.

Accounts are created without any credential: a row activates the first time
its owner signs in with Google (routers/auth.py), which is when
supabase_user_id is set.
"""
from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.audit import ACTION_ADMIN_CREATE_USER, ACTION_ADMIN_DELETE_USER, ACTION_ADMIN_UPDATE_USER, record_audit
from app.deps import CurrentUser, get_client_ip, get_db, require_admin, require_role
from app.models import Role, UserStatus
from app.schemas import AdminCreateUserRequest, AdminUpdateUserRequest, UserOut
from app.security import is_allowed_domain, is_student_shaped_local_part, local_part_of, normalize_email
from app.services.users import USER_COLUMNS, row_to_user

router = APIRouter(prefix="/api/admin/users", tags=["admin"])

# Exam Controllers list teachers to assign invigilators; nothing else.
require_user_lister = require_role(Role.ADMIN, Role.EXAM_CONTROLLER)

ERR_NON_UNIVERSITY_EMAIL = "Please use the university email domain."
ERR_STUDENT_ROLE_NON_NUMERIC = "role=student requires a six-digit registration-number email."
ERR_STAFF_ROLE_NUMERIC = "Staff roles cannot use a six-digit (student-shaped) email."
ERR_CONFLICT = "Email or registration/employee number already in use."
ERR_NOT_FOUND = "User not found."


def _validate_email_role_pairing(email: str, role: Role) -> None:
    if not is_allowed_domain(email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERR_NON_UNIVERSITY_EMAIL)
    student_shaped = is_student_shaped_local_part(local_part_of(email))
    if role == Role.STUDENT and not student_shaped:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERR_STUDENT_ROLE_NON_NUMERIC)
    if role != Role.STUDENT and student_shaped:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERR_STAFF_ROLE_NUMERIC)


@router.get("", response_model=list[UserOut])
async def list_users(
    role: Role | None = None,
    user_status: UserStatus | None = Query(default=None, alias="status"),
    current_user: CurrentUser = Depends(require_user_lister),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[UserOut]:
    if current_user.role == Role.EXAM_CONTROLLER:
        if role not in (None, Role.TEACHER):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Exam Controllers can only list teachers.")
        role = Role.TEACHER
    rows = await conn.fetch(
        f"""
        SELECT {USER_COLUMNS} FROM users
        WHERE deleted_at IS NULL
          AND ($1::text IS NULL OR role = $1)
          AND ($2::text IS NULL OR status = $2)
        ORDER BY full_name
        """,
        role.value if role else None,
        user_status.value if user_status else None,
    )
    return [row_to_user(row) for row in rows]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def admin_create_user(
    body: AdminCreateUserRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_db),
) -> UserOut:
    email = normalize_email(body.email)
    _validate_email_role_pairing(email, body.role)

    try:
        row = await conn.fetchrow(
            f"""
            INSERT INTO users (full_name, email, role, department, registration_or_employee_no, status)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING {USER_COLUMNS}
            """,
            body.full_name.strip(),
            email,
            body.role.value,
            body.department.strip(),
            local_part_of(email),
            body.status.value,
        )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERR_CONFLICT) from exc

    await record_audit(
        conn,
        actor_id=current_user.user_id,
        action=ACTION_ADMIN_CREATE_USER,
        target=email,
        new_value={"role": body.role.value, "department": body.department.strip(), "status": body.status.value},
        ip_address=get_client_ip(request),
    )
    return row_to_user(row)


@router.patch("/{user_id}", response_model=UserOut)
async def admin_update_user(
    user_id: UUID,
    body: AdminUpdateUserRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_db),
) -> UserOut:
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    async with conn.transaction():
        existing = await conn.fetchrow(
            f"SELECT {USER_COLUMNS} FROM users WHERE id = $1 AND deleted_at IS NULL FOR UPDATE", user_id
        )
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)

        new_email = normalize_email(changes["email"]) if "email" in changes else existing["email"]
        new_role = Role(changes.get("role", existing["role"]))
        if new_email != existing["email"] and existing["activated"]:
            # The email is what matched the owner's Google identity; changing it
            # after activation would strand or reassign the account.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The email of an account that has already signed in cannot be changed.",
            )
        _validate_email_role_pairing(new_email, new_role)

        is_self = str(user_id) == current_user.user_id
        if is_self and (new_role != Role.ADMIN or changes.get("status", UserStatus.ACTIVE) != UserStatus.ACTIVE):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot remove your own admin role or deactivate your own account.",
            )

        try:
            row = await conn.fetchrow(
                f"""
                UPDATE users SET full_name = $2, email = $3, role = $4, department = $5, status = $6,
                                 registration_or_employee_no = $7
                WHERE id = $1
                RETURNING {USER_COLUMNS}
                """,
                user_id,
                changes.get("full_name", existing["full_name"]).strip(),
                new_email,
                new_role.value,
                changes.get("department", existing["department"]).strip(),
                UserStatus(changes.get("status", existing["status"])).value,
                local_part_of(new_email),
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERR_CONFLICT) from exc

        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_ADMIN_UPDATE_USER,
            target=str(user_id),
            new_value={key: (value.value if hasattr(value, "value") else value) for key, value in changes.items()},
            ip_address=get_client_ip(request),
        )
    return row_to_user(row)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_user(
    user_id: UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_db),
) -> Response:
    """Soft delete: access ends immediately (deps re-checks every request),
    while the cases, penalties and audit entries that reference the row keep
    their integrity. The email stays reserved so it can never be re-linked.
    """
    if str(user_id) == current_user.user_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You cannot delete your own account.")
    async with conn.transaction():
        deleted = await conn.fetchval(
            """
            UPDATE users SET deleted_at = now(), status = 'disabled'
            WHERE id = $1 AND deleted_at IS NULL
            RETURNING email
            """,
            user_id,
        )
        if deleted is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_ADMIN_DELETE_USER,
            target=str(user_id),
            new_value={"email": deleted},
            ip_address=get_client_ip(request),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
