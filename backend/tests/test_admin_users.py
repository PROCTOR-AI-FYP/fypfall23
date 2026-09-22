"""Security checklist: admin-create cannot pair role=student with a
non-numeric email, or a staff role with a six-digit-numeric email.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _admin_token(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/login", json={"email": "admin.registrar@students.au.edu.pk", "password": "ChangeMe123!"}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def test_admin_create_rejects_student_role_with_non_numeric_email(client: AsyncClient) -> None:
    token = await _admin_token(client)
    resp = await client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "full_name": "Should Fail",
            "email": "not.numeric@students.au.edu.pk",
            "password_or_send_setup_email": "SetupPass1!",
            "role": "student",
        },
    )
    assert resp.status_code == 422


async def test_admin_create_rejects_staff_role_with_six_digit_email(client: AsyncClient) -> None:
    token = await _admin_token(client)
    resp = await client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "full_name": "Should Also Fail",
            "email": "999999@students.au.edu.pk",
            "password_or_send_setup_email": "SetupPass1!",
            "role": "teacher",
        },
    )
    assert resp.status_code == 422


async def test_admin_create_accepts_valid_staff_pairing(client: AsyncClient) -> None:
    token = await _admin_token(client)
    resp = await client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "full_name": "New Teacher",
            "email": "a.khan@students.au.edu.pk",
            "password_or_send_setup_email": "SetupPass1!",
            "role": "teacher",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "teacher"
    assert body["email_verified"] is True


async def test_admin_create_requires_authentication(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/admin/users",
        json={
            "full_name": "No Token",
            "email": "b.qureshi@students.au.edu.pk",
            "password_or_send_setup_email": "SetupPass1!",
            "role": "teacher",
        },
    )
    assert resp.status_code == 401


async def test_admin_create_rejects_non_admin_caller(client: AsyncClient) -> None:
    login_resp = await client.post(
        "/api/auth/login", json={"email": "m.bilal@students.au.edu.pk", "password": "ChangeMe123!"}
    )
    token = login_resp.json()["access_token"]
    resp = await client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "full_name": "Blocked",
            "email": "c.malik@students.au.edu.pk",
            "password_or_send_setup_email": "SetupPass1!",
            "role": "teacher",
        },
    )
    assert resp.status_code == 403
