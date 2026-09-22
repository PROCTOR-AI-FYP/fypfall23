"""Security checklist items covered here:
- Signup cannot produce any role other than student under any request body.
- Signup: identical response body+status for new/existing-unverified/existing-verified.
- Redis rate limit: 6th signup attempt from one IP in an hour returns 429.
- users.registration_or_employee_no UNIQUE: duplicate signup after first is verified is rejected.
"""
from __future__ import annotations

import asyncpg
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

NEW_STUDENT_EMAIL = "998877@students.au.edu.pk"


async def test_signup_ignores_role_field_always_produces_student(
    client: AsyncClient, admin_conn: asyncpg.Connection
) -> None:
    response = await client.post(
        "/api/auth/signup",
        json={
            "full_name": "New Student",
            "email": NEW_STUDENT_EMAIL,
            "password": "SuperSecret1!",
            "role": "admin",  # attempted privilege escalation via extra field
        },
    )
    assert response.status_code == 202

    row = await admin_conn.fetchrow("SELECT role FROM users WHERE email = $1", NEW_STUDENT_EMAIL)
    assert row is not None
    assert row["role"] == "student"


async def test_signup_identical_response_for_new_unverified_and_verified(client: AsyncClient) -> None:
    email = "554433@students.au.edu.pk"
    payload = {"full_name": "Case Student", "email": email, "password": "SuperSecret1!"}

    resp_new = await client.post("/api/auth/signup", json=payload)
    resp_existing_unverified = await client.post("/api/auth/signup", json=payload)

    # Seeded, already-verified student (232475) — same shape must come back.
    resp_existing_verified = await client.post(
        "/api/auth/signup",
        json={"full_name": "Ayesha Raza", "email": "232475@students.au.edu.pk", "password": "SuperSecret1!"},
    )

    assert resp_new.status_code == resp_existing_unverified.status_code == resp_existing_verified.status_code == 202
    assert resp_new.json() == resp_existing_unverified.json() == resp_existing_verified.json()


async def test_signup_rate_limit_sixth_attempt_from_same_ip_is_429(client: AsyncClient) -> None:
    responses = []
    for i in range(6):
        email = f"10000{i}@students.au.edu.pk"
        resp = await client.post(
            "/api/auth/signup",
            json={"full_name": f"Student {i}", "email": email, "password": "SuperSecret1!"},
        )
        responses.append(resp)

    assert [r.status_code for r in responses[:5]] == [202] * 5
    assert responses[5].status_code == 429


async def test_duplicate_signup_same_reg_no_after_verified_is_rejected_not_merged(
    client: AsyncClient, admin_conn: asyncpg.Connection
) -> None:
    email = "667788@students.au.edu.pk"
    await client.post(
        "/api/auth/signup", json={"full_name": "First Owner", "email": email, "password": "SuperSecret1!"}
    )
    # Verify the first account directly (bypassing needing the raw token) by
    # marking it verified, simulating the user having clicked the link.
    await admin_conn.execute("UPDATE users SET email_verified = true WHERE email = $1", email)

    before_count = await admin_conn.fetchval(
        "SELECT count(*) FROM users WHERE registration_or_employee_no = '667788'"
    )
    assert before_count == 1

    # A second signup attempt with the same six digits but a different email
    # domain-local mapping is impossible (local part IS the reg no), so the
    # only way to hit this is the exact same email — which our identical
    # 202-response path treats as a no-op since it's already verified.
    resp = await client.post(
        "/api/auth/signup", json={"full_name": "Impersonator", "email": email, "password": "OtherPass1!"}
    )
    assert resp.status_code == 202

    after_count = await admin_conn.fetchval(
        "SELECT count(*) FROM users WHERE registration_or_employee_no = '667788'"
    )
    assert after_count == 1  # no second row created; not merged, not duplicated

    # Password was NOT overwritten by the "impersonator" attempt.
    stored_hash = await admin_conn.fetchval("SELECT password_hash FROM users WHERE email = $1", email)
    from app.security import verify_password

    assert verify_password("SuperSecret1!", stored_hash)
    assert not verify_password("OtherPass1!", stored_hash)


async def test_registration_or_employee_no_unique_constraint_enforced_at_db_level(
    admin_conn: asyncpg.Connection,
) -> None:
    """Direct proof the UNIQUE constraint exists: two different emails can
    never share a registration_or_employee_no, which is what makes the
    signup-dedup behaviour above a real guarantee rather than incidental.
    """
    await admin_conn.execute(
        """
        INSERT INTO users (full_name, email, password_hash, role, registration_or_employee_no, status, email_verified)
        VALUES ('Original', 'aaa111@students.au.edu.pk', 'x', 'student', '111222', 'active', true)
        """
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await admin_conn.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role, registration_or_employee_no, status, email_verified)
            VALUES ('Duplicate Reg No', 'bbb222@students.au.edu.pk', 'x', 'student', '111222', 'active', true)
            """
        )
