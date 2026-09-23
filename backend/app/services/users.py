"""Shared user-row selection and serialization.

USER_COLUMNS never includes password_hash or supabase_user_id; activation
is derived in SQL so the raw identity id is never loaded for a response.
"""
from __future__ import annotations

import asyncpg

from app.models import Role, UserStatus
from app.schemas import UserOut

USER_COLUMNS = (
    "id, full_name, email, role, department, registration_or_employee_no, status, "
    "(supabase_user_id IS NOT NULL) AS activated, created_at"
)


def row_to_user(row: asyncpg.Record) -> UserOut:
    return UserOut(
        id=str(row["id"]),
        full_name=row["full_name"],
        email=row["email"],
        role=Role(row["role"]),
        department=row["department"],
        registration_or_employee_no=row["registration_or_employee_no"],
        status=UserStatus(row["status"]),
        activated=row["activated"],
        created_at=row["created_at"],
    )


async def fetch_user(conn: asyncpg.Connection, user_id: str) -> UserOut | None:
    row = await conn.fetchrow(
        f"SELECT {USER_COLUMNS} FROM users WHERE id = $1::uuid AND deleted_at IS NULL", user_id
    )
    return row_to_user(row) if row is not None else None
