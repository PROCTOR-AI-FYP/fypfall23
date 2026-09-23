"""Phase 4 security re-verification: removed auth paths stay removed, RLS
scopes every student-facing table at the database level, the Supabase Data
API roles can reach nothing, the app role holds only what the code needs, and
no response ever carries a password hash or a linked identity id.
"""
from __future__ import annotations

import asyncpg
import pytest
from httpx import AsyncClient

from tests.conftest import BACKEND_DIR, _apply_sql_file
from tests.helpers import ADMIN_EMAIL, CONTROLLER_EMAIL, HOD_EMAIL, STUDENT_A_EMAIL, STUDENT_B_EMAIL, TEACHER_EMAIL, auth, login
from tests.test_role_isolation import ENDPOINTS

APP_TABLES = [
    "users", "classrooms", "exam_sessions", "seat_assignments", "cases", "detection_events", "penalties",
    "appeals", "notifications", "detection_thresholds", "audit_log",
]


@pytest.mark.parametrize("path", ["/api/auth/signup", "/api/auth/verify-email", "/api/auth/resend-verification", "/api/auth/login"])
async def test_password_era_endpoints_are_gone(client: AsyncClient, path: str) -> None:
    response = await client.post(path, json={"email": "232475@students.au.edu.pk", "password": "ChangeMe123!", "token": "x"})
    assert response.status_code == 404


async def test_no_response_leaks_hashes_or_identity_ids(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    # Give every account a hash as if left over from the password era, and activate all.
    await admin_conn.execute("UPDATE users SET password_hash = '$2b$12$leftoverhash', supabase_user_id = COALESCE(supabase_user_id, gen_random_uuid())")
    case_id = str(await admin_conn.fetchval("SELECT id FROM cases WHERE reference_no = 'AU-CS-INT-2026-014'"))
    teacher_id = str(await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", TEACHER_EMAIL))
    identities = [str(r["supabase_user_id"]) for r in await admin_conn.fetch("SELECT supabase_user_id FROM users")]
    checked = 0
    for email in (ADMIN_EMAIL, HOD_EMAIL, TEACHER_EMAIL, CONTROLLER_EMAIL, STUDENT_A_EMAIL):
        headers = auth(await login(client, email))
        for method, template, _ in ENDPOINTS:
            if method != "GET":
                continue
            response = await client.get(template.format(case=case_id, teacher=teacher_id), headers=headers)
            if response.status_code != 200:
                continue
            checked += 1
            assert "password" not in response.text and "leftoverhash" not in response.text, template
            assert "supabase_user_id" not in response.text, template
            assert not any(identity in response.text for identity in identities), template
    assert checked > 20


async def test_rls_scopes_penalties_and_appeals_per_student(
    admin_conn: asyncpg.Connection, low_priv_conn: asyncpg.Connection
) -> None:
    hod = await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", HOD_EMAIL)
    students = {}
    for email, reference in ((STUDENT_A_EMAIL, "AU-CS-INT-2026-014"), (STUDENT_B_EMAIL, "AU-CS-INT-2026-015")):
        student_id = await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", email)
        case_id = await admin_conn.fetchval("UPDATE cases SET status = 'confirmed' WHERE reference_no = $1 RETURNING id", reference)
        await admin_conn.execute(
            "INSERT INTO penalties (case_id, penalty_type, description, issued_by, notice_reference) VALUES ($1, 'formal_warning', 'w', $2, $3)",
            case_id, hod, reference,
        )
        await admin_conn.execute("INSERT INTO appeals (case_id, student_id, statement) VALUES ($1, $2, 'appeal')", case_id, student_id)
        students[email] = (student_id, reference)

    a_id, a_ref = students[STUDENT_A_EMAIL]
    b_id, _ = students[STUDENT_B_EMAIL]
    async with low_priv_conn.transaction():
        await low_priv_conn.execute("SELECT set_config('app.current_role', 'student', true)")
        await low_priv_conn.execute("SELECT set_config('app.current_user_id', $1, true)", str(a_id))
        assert [r["notice_reference"] for r in await low_priv_conn.fetch("SELECT notice_reference FROM penalties")] == [a_ref]
        assert [r["student_id"] for r in await low_priv_conn.fetch("SELECT student_id FROM appeals")] == [a_id]
        # Nor can a student write an appeal in someone else's name.
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await low_priv_conn.execute(
                "INSERT INTO appeals (case_id, student_id, statement) SELECT case_id, $1, 'forged' FROM penalties LIMIT 1", b_id
            )
    async with low_priv_conn.transaction():
        await low_priv_conn.execute("SELECT set_config('app.current_role', 'hod', true)")
        await low_priv_conn.execute("SELECT set_config('app.current_user_id', $1, true)", str(hod))
        assert await low_priv_conn.fetchval("SELECT count(*) FROM penalties") == 2
        assert await low_priv_conn.fetchval("SELECT count(*) FROM appeals") == 2


async def test_student_with_no_session_variables_sees_nothing_personal(low_priv_conn: asyncpg.Connection) -> None:
    """A connection that claims the student role but no user id matches no rows (fails closed)."""
    async with low_priv_conn.transaction():
        await low_priv_conn.execute("SELECT set_config('app.current_role', 'student', true)")
        for table in ("cases", "penalties", "appeals", "notifications"):
            assert await low_priv_conn.fetchval(f"SELECT count(*) FROM {table}") == 0, table


async def test_app_role_cannot_delete_evidence_or_users(low_priv_conn: asyncpg.Connection) -> None:
    for table in ("users", "cases", "penalties", "appeals", "detection_events", "exam_sessions", "audit_log"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await low_priv_conn.execute(f"DELETE FROM {table}")


async def test_data_api_roles_reach_no_table_now_or_later(admin_conn: asyncpg.Connection) -> None:
    for role in ("anon", "authenticated"):
        if not await admin_conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role):
            await admin_conn.execute(f'CREATE ROLE "{role}" NOLOGIN')
        await admin_conn.execute(f'GRANT ALL ON ALL TABLES IN SCHEMA public TO "{role}"')  # Supabase's default posture
        await admin_conn.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{role}"')

    await _apply_sql_file(admin_conn, BACKEND_DIR / "db" / "schema.sql")
    await admin_conn.execute("CREATE TABLE IF NOT EXISTS security_probe_future_table (id int)")
    try:
        for role in ("anon", "authenticated"):
            for table in [*APP_TABLES, "security_probe_future_table"]:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not await admin_conn.fetchval("SELECT has_table_privilege($1, $2, $3)", role, table, privilege), (role, table, privilege)
    finally:
        await admin_conn.execute("DROP TABLE security_probe_future_table")


async def test_password_hash_column_is_optional_and_unused(admin_conn: asyncpg.Connection) -> None:
    assert await admin_conn.fetchval(
        "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'password_hash'"
    ) == "YES"
    assert not await admin_conn.fetchval("SELECT to_regclass('public.email_verifications')")
