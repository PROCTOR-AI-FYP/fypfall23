"""User management: admin-create pairs roles with email shapes and takes no
credential; listing exposes activation but never the linked identity; soft
delete and self-lockout guards.
"""
from __future__ import annotations

import asyncpg
from httpx import AsyncClient

from tests.helpers import ADMIN_EMAIL, CONTROLLER_EMAIL, HOD_EMAIL, STUDENT_A_EMAIL, TEACHER_EMAIL, auth, login


def _new_user(email: str, role: str, **extra: str) -> dict[str, str]:
    return {"full_name": "New Person", "email": email, "role": role, "department": "Computer Science", **extra}


async def test_admin_create_rejects_student_role_with_non_numeric_email(client: AsyncClient) -> None:
    admin = auth(await login(client, ADMIN_EMAIL))
    resp = await client.post("/api/admin/users", headers=admin, json=_new_user("not.numeric@students.au.edu.pk", "student"))
    assert resp.status_code == 422


async def test_admin_create_rejects_staff_role_with_six_digit_email(client: AsyncClient) -> None:
    admin = auth(await login(client, ADMIN_EMAIL))
    resp = await client.post("/api/admin/users", headers=admin, json=_new_user("999999@students.au.edu.pk", "teacher"))
    assert resp.status_code == 422


async def test_admin_create_rejects_other_domains_and_password_fields(client: AsyncClient) -> None:
    admin = auth(await login(client, ADMIN_EMAIL))
    other_domain = await client.post("/api/admin/users", headers=admin, json=_new_user("x.y@gmail.com", "teacher"))
    assert other_domain.status_code == 422
    # There is no password anywhere any more; a client still sending one is refused, not ignored.
    with_password = await client.post(
        "/api/admin/users", headers=admin,
        json=_new_user("a.khan@students.au.edu.pk", "teacher", password_or_send_setup_email="SetupPass1!"),
    )
    assert with_password.status_code == 422


async def test_admin_create_accepts_valid_staff_pairing(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    admin = auth(await login(client, ADMIN_EMAIL))
    resp = await client.post("/api/admin/users", headers=admin, json=_new_user("A.Khan@students.au.edu.pk", "teacher"))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["role"] == "teacher"
    assert body["email"] == "a.khan@students.au.edu.pk"
    assert body["department"] == "Computer Science"
    assert body["activated"] is False  # activates on first Google sign-in
    assert "supabase_user_id" not in body and "password_hash" not in body

    row = await admin_conn.fetchrow("SELECT password_hash, supabase_user_id FROM users WHERE id = $1::uuid", body["id"])
    assert row["password_hash"] is None and row["supabase_user_id"] is None
    assert await admin_conn.fetchval(
        "SELECT count(*) FROM audit_log WHERE action = 'admin_create_user' AND target = 'a.khan@students.au.edu.pk'"
    ) == 1

    duplicate = await client.post("/api/admin/users", headers=admin, json=_new_user("a.khan@students.au.edu.pk", "hod"))
    assert duplicate.status_code == 409


async def test_admin_create_requires_authentication(client: AsyncClient) -> None:
    resp = await client.post("/api/admin/users", json=_new_user("b.qureshi@students.au.edu.pk", "teacher"))
    assert resp.status_code == 401


async def test_admin_create_rejects_non_admin_caller(client: AsyncClient) -> None:
    for email in (TEACHER_EMAIL, HOD_EMAIL, CONTROLLER_EMAIL, STUDENT_A_EMAIL):
        token = await login(client, email)
        resp = await client.post("/api/admin/users", headers=auth(token), json=_new_user("c.malik@students.au.edu.pk", "teacher"))
        assert resp.status_code == 403, email


async def test_listing_shows_activation_but_never_the_identity(client: AsyncClient) -> None:
    admin = auth(await login(client, ADMIN_EMAIL))
    users = (await client.get("/api/admin/users", headers=admin)).json()
    by_email = {user["email"]: user for user in users}
    assert by_email[STUDENT_A_EMAIL]["activated"] is True  # conftest activates seeded students
    assert by_email[TEACHER_EMAIL]["activated"] is False
    assert all("supabase_user_id" not in user and "password_hash" not in user for user in users)

    teachers = (await client.get("/api/admin/users?role=teacher", headers=admin)).json()
    assert {user["role"] for user in teachers} == {"teacher"}


async def test_exam_controller_can_list_only_teachers(client: AsyncClient) -> None:
    controller = auth(await login(client, CONTROLLER_EMAIL))
    listed = await client.get("/api/admin/users", headers=controller)
    assert listed.status_code == 200
    assert {user["role"] for user in listed.json()} == {"teacher"}
    assert (await client.get("/api/admin/users?role=student", headers=controller)).status_code == 403
    for email in (TEACHER_EMAIL, HOD_EMAIL, STUDENT_A_EMAIL):
        assert (await client.get("/api/admin/users", headers=auth(await login(client, email)))).status_code == 403


async def test_update_rules(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    admin_token = await login(client, ADMIN_EMAIL)
    admin = auth(admin_token)
    teacher_id = str(await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", TEACHER_EMAIL))
    student_id = str(await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", STUDENT_A_EMAIL))
    admin_id = str(await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", ADMIN_EMAIL))

    renamed = await client.patch(f"/api/admin/users/{teacher_id}", headers=admin, json={"full_name": "Dr. Muhammad Bilal", "department": "Software Engineering"})
    assert renamed.status_code == 200 and renamed.json()["department"] == "Software Engineering"

    # Not yet activated -> email may still be corrected.
    moved = await client.patch(f"/api/admin/users/{teacher_id}", headers=admin, json={"email": "muhammad.bilal@students.au.edu.pk"})
    assert moved.status_code == 200
    # Activated -> the email is the identity anchor and is frozen.
    frozen = await client.patch(f"/api/admin/users/{student_id}", headers=admin, json={"email": "232476@students.au.edu.pk"})
    assert frozen.status_code == 409
    # Role changes must still respect the email shape.
    assert (await client.patch(f"/api/admin/users/{student_id}", headers=admin, json={"role": "teacher"})).status_code == 422

    # No self-lockout.
    assert (await client.patch(f"/api/admin/users/{admin_id}", headers=admin, json={"role": "hod"})).status_code == 409
    assert (await client.patch(f"/api/admin/users/{admin_id}", headers=admin, json={"status": "disabled"})).status_code == 409
    assert (await client.delete(f"/api/admin/users/{admin_id}", headers=admin)).status_code == 409

    assert await admin_conn.fetchval("SELECT count(*) FROM audit_log WHERE action = 'admin_update_user'") == 2


async def test_disable_and_delete_end_access_immediately(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    admin = auth(await login(client, ADMIN_EMAIL))
    teacher_token = await login(client, TEACHER_EMAIL)
    teacher_id = str(await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", TEACHER_EMAIL))
    assert (await client.get("/api/auth/me", headers=auth(teacher_token))).status_code == 200

    await client.patch(f"/api/admin/users/{teacher_id}", headers=admin, json={"status": "disabled"})
    # The still-unexpired token stops working on the very next request.
    assert (await client.get("/api/auth/me", headers=auth(teacher_token))).status_code == 401
    await client.patch(f"/api/admin/users/{teacher_id}", headers=admin, json={"status": "active"})
    assert (await client.get("/api/auth/me", headers=auth(teacher_token))).status_code == 200

    deleted = await client.delete(f"/api/admin/users/{teacher_id}", headers=admin)
    assert deleted.status_code == 204
    assert (await client.get("/api/auth/me", headers=auth(teacher_token))).status_code == 401
    listed = (await client.get("/api/admin/users", headers=admin)).json()
    assert TEACHER_EMAIL not in {user["email"] for user in listed}
    # Soft delete: the row, and everything that references it, survives.
    assert await admin_conn.fetchval("SELECT deleted_at IS NOT NULL FROM users WHERE id = $1::uuid", teacher_id)
    assert await admin_conn.fetchval("SELECT count(*) FROM exam_sessions WHERE invigilator_id = $1::uuid", teacher_id) == 1
    assert (await client.delete(f"/api/admin/users/{teacher_id}", headers=admin)).status_code == 404


async def test_role_change_applies_on_next_request(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    """The JWT's role claim is never trusted; the database role is."""
    admin = auth(await login(client, ADMIN_EMAIL))
    hod_token = await login(client, HOD_EMAIL)
    hod_id = str(await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", HOD_EMAIL))
    assert (await client.get("/api/admin/users", headers=auth(hod_token))).status_code == 403
    await client.patch(f"/api/admin/users/{hod_id}", headers=admin, json={"role": "admin"})
    assert (await client.get("/api/admin/users", headers=auth(hod_token))).status_code == 200
