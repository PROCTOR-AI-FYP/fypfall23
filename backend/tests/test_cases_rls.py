"""Security checklist: two seeded students; student A cannot see student B's
cases via GET /api/cases, asserted both through the API response and via a
direct query executed as the low-privilege DB role with RLS active.
"""
from __future__ import annotations

import asyncpg
from httpx import AsyncClient

from tests.helpers import STUDENT_A_EMAIL, STUDENT_B_EMAIL, auth, login


async def test_student_a_cannot_see_student_b_case_via_api(client: AsyncClient) -> None:
    token_a = await login(client, STUDENT_A_EMAIL)

    resp = await client.get("/api/cases", headers=auth(token_a))
    assert resp.status_code == 200
    cases = resp.json()

    assert len(cases) >= 1
    assert all(c["reference_no"] != "AU-CS-INT-2026-015" for c in cases)
    assert any(c["reference_no"] == "AU-CS-INT-2026-014" for c in cases)


async def test_rls_blocks_cross_student_visibility_at_db_level(
    low_priv_conn: asyncpg.Connection, admin_conn: asyncpg.Connection
) -> None:
    student_a_id = await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", STUDENT_A_EMAIL)
    student_b_id = await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", STUDENT_B_EMAIL)

    async with low_priv_conn.transaction():
        await low_priv_conn.execute("SELECT set_config('app.current_role', 'student', true)")
        await low_priv_conn.execute("SELECT set_config('app.current_user_id', $1, true)", str(student_a_id))

        visible_rows = await low_priv_conn.fetch("SELECT student_id, reference_no FROM cases")

        assert len(visible_rows) >= 1
        assert all(str(row["student_id"]) == str(student_a_id) for row in visible_rows)
        assert all(str(row["student_id"]) != str(student_b_id) for row in visible_rows)


async def test_rls_allows_non_student_roles_to_see_all_cases(low_priv_conn: asyncpg.Connection) -> None:
    async with low_priv_conn.transaction():
        await low_priv_conn.execute("SELECT set_config('app.current_role', 'hod', true)")
        await low_priv_conn.execute("SELECT set_config('app.current_user_id', '', true)")

        visible_rows = await low_priv_conn.fetch("SELECT reference_no FROM cases")
        refs = {row["reference_no"] for row in visible_rows}
        assert {"AU-CS-INT-2026-014", "AU-CS-INT-2026-015"}.issubset(refs)
