"""Security checklist: verification tokens — consumed/expired/nonexistent
all return an identical generic 400.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncpg
import pytest
from httpx import AsyncClient

from app.security import hash_token

pytestmark = pytest.mark.asyncio


async def _make_verification_row(
    admin_conn: asyncpg.Connection, *, user_email: str, consumed: bool, expired: bool
) -> str:
    user_id = await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", user_email)
    raw_token = f"token-for-{user_email}-{consumed}-{expired}"
    expires_at = (
        datetime.now(timezone.utc) - timedelta(hours=1)
        if expired
        else datetime.now(timezone.utc) + timedelta(hours=1)
    )
    consumed_at = datetime.now(timezone.utc) if consumed else None
    await admin_conn.execute(
        """
        INSERT INTO email_verifications (user_id, token_hash, expires_at, consumed_at)
        VALUES ($1, $2, $3, $4)
        """,
        user_id,
        hash_token(raw_token),
        expires_at,
        consumed_at,
    )
    return raw_token


async def test_verify_email_identical_generic_400_for_all_failure_modes(
    client: AsyncClient, admin_conn: asyncpg.Connection
) -> None:
    consumed_token = await _make_verification_row(
        admin_conn, user_email="232475@students.au.edu.pk", consumed=True, expired=False
    )
    expired_token = await _make_verification_row(
        admin_conn, user_email="232490@students.au.edu.pk", consumed=False, expired=True
    )
    nonexistent_token = "this-token-was-never-issued"

    resp_consumed = await client.post("/api/auth/verify-email", json={"token": consumed_token})
    resp_expired = await client.post("/api/auth/verify-email", json={"token": expired_token})
    resp_nonexistent = await client.post("/api/auth/verify-email", json={"token": nonexistent_token})

    assert resp_consumed.status_code == resp_expired.status_code == resp_nonexistent.status_code == 400
    assert resp_consumed.json()["detail"] == resp_expired.json()["detail"] == resp_nonexistent.json()["detail"]


async def test_verify_email_success_marks_user_verified(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    signup_resp = await client.post(
        "/api/auth/signup",
        json={"full_name": "Fresh Student", "email": "112233@students.au.edu.pk", "password": "SuperSecret1!"},
    )
    assert signup_resp.status_code == 202

    # Pull the token straight out of the DB (console email sender only logs
    # it) by regenerating what we know the row looks like: fetch token_hash
    # and confirm the flow using a manually inserted matching token instead,
    # since the raw token itself is never persisted.
    user_id = await admin_conn.fetchval(
        "SELECT id FROM users WHERE email = $1", "112233@students.au.edu.pk"
    )
    raw_token = "known-raw-token-for-test"
    await admin_conn.execute("DELETE FROM email_verifications WHERE user_id = $1", user_id)
    await admin_conn.execute(
        """
        INSERT INTO email_verifications (user_id, token_hash, expires_at)
        VALUES ($1, $2, now() + interval '1 hour')
        """,
        user_id,
        hash_token(raw_token),
    )

    resp = await client.post("/api/auth/verify-email", json={"token": raw_token})
    assert resp.status_code == 200

    verified = await admin_conn.fetchval("SELECT email_verified FROM users WHERE id = $1", user_id)
    assert verified is True

    # Re-using the same token must fail identically to any other bad token.
    resp_again = await client.post("/api/auth/verify-email", json={"token": raw_token})
    assert resp_again.status_code == 400
