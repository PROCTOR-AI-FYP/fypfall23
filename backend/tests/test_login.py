"""Security checklist:
- Wrong password on an unverified account returns the SAME generic
  invalid-credentials message as wrong password on a verified account.
- JWT role claim is read from the users table at issuance (grepped for in
  test_no_cached_role_path, plus an end-to-end assertion here).
"""
from __future__ import annotations

import inspect

import asyncpg
import jwt as pyjwt
import pytest
from httpx import AsyncClient

from app.config import settings
from app.routers import auth as auth_router

pytestmark = pytest.mark.asyncio


async def test_wrong_password_same_message_verified_and_unverified(
    client: AsyncClient, admin_conn: asyncpg.Connection
) -> None:
    # Verified seeded account.
    resp_verified = await client.post(
        "/api/auth/login", json={"email": "232475@students.au.edu.pk", "password": "definitely-wrong"}
    )

    # Unverified account.
    await client.post(
        "/api/auth/signup",
        json={"full_name": "Unverified Student", "email": "445566@students.au.edu.pk", "password": "SuperSecret1!"},
    )
    resp_unverified = await client.post(
        "/api/auth/login", json={"email": "445566@students.au.edu.pk", "password": "definitely-wrong"}
    )

    assert resp_verified.status_code == resp_unverified.status_code == 401
    assert resp_verified.json()["detail"] == resp_unverified.json()["detail"]
    assert "verify" not in resp_verified.json()["detail"].lower()
    assert "verify" not in resp_unverified.json()["detail"].lower()


async def test_correct_password_unverified_account_gets_verify_email_message(client: AsyncClient) -> None:
    await client.post(
        "/api/auth/signup",
        json={"full_name": "Unverified Student", "email": "778899@students.au.edu.pk", "password": "SuperSecret1!"},
    )
    resp = await client.post(
        "/api/auth/login", json={"email": "778899@students.au.edu.pk", "password": "SuperSecret1!"}
    )
    assert resp.status_code == 403
    assert "verify" in resp.json()["detail"].lower()


async def test_login_success_role_claim_matches_db_row(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": "hod.cs@students.au.edu.pk", "password": "ChangeMe123!"}
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    decoded = pyjwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

    db_role = await admin_conn.fetchval("SELECT role FROM users WHERE email = $1", "hod.cs@students.au.edu.pk")
    assert decoded["role"] == db_role == "hod"


def test_no_cached_role_path_in_login_source() -> None:
    """Static proof that login's JWT is created from a role variable derived
    from the just-fetched DB row in this same request, not from any request
    body field, cache, or global.
    """
    source = inspect.getsource(auth_router.login)
    assert "role = Role(user[" in source
    assert "create_access_token(user_id=str(user[\"id\"]), role=role)" in source
    assert "body.role" not in source  # LoginRequest has no role field either
