"""Security checklist: seatmap upload never creates a seat_assignments row
for an unresolved or unverified registration number.
"""
from __future__ import annotations

import io

import asyncpg
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

SESSION_ID = "00000000-0000-0000-0000-000000000001"


async def _controller_token(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/login", json={"email": "controller.exams@students.au.edu.pk", "password": "ChangeMe123!"}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def test_seatmap_resolves_verified_rejects_unregistered_and_unverified(
    client: AsyncClient, admin_conn: asyncpg.Connection
) -> None:
    await client.post(
        "/api/auth/signup",
        json={"full_name": "Unverified Seatmap Student", "email": "321321@students.au.edu.pk", "password": "SuperSecret1!"},
    )

    csv_content = (
        "seat_number,student_reg_no\n"
        "20,232475\n"          # verified seeded student -> Resolved
        "21,000000\n"          # no such user -> Unregistered ID
        "22,321321\n"          # exists but unverified -> Unverified
    )

    token = await _controller_token(client)
    files = {"file": ("seatmap.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    resp = await client.post(
        f"/api/sessions/{SESSION_ID}/seatmap",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
    )
    assert resp.status_code == 200
    body = resp.json()

    statuses = {row["seat_number"]: row["status"] for row in body["rows"]}
    assert statuses[20] == "Resolved"
    assert statuses[21] == "Unregistered ID"
    assert statuses[22] == "Unverified"
    assert body["resolved_count"] == 1
    assert body["rejected_count"] == 2

    rows_in_db = await admin_conn.fetch(
        "SELECT seat_number FROM seat_assignments WHERE session_id = $1 AND seat_number IN (20, 21, 22)",
        SESSION_ID,
    )
    seats_persisted = {r["seat_number"] for r in rows_in_db}
    assert seats_persisted == {20}  # only the resolved row was written
