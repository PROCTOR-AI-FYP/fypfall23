"""Security checklist: seatmap upload never creates a seat_assignments row
for an unregistered registration number, or for a student account whose
owner has never signed in (activated) with Google.
"""
from __future__ import annotations

import io

import asyncpg
from httpx import AsyncClient

from tests.helpers import CONTROLLER_EMAIL, SEEDED_SESSION_ID, auth, login


async def test_seatmap_resolves_activated_rejects_unregistered_and_unactivated(
    client: AsyncClient, admin_conn: asyncpg.Connection
) -> None:
    # Created by an Admin, never signed in.
    await admin_conn.execute(
        """
        INSERT INTO users (full_name, email, role, registration_or_employee_no)
        VALUES ('Unactivated Seatmap Student', '321321@students.au.edu.pk', 'student', '321321')
        """
    )

    csv_content = (
        "seat_number,student_reg_no\n"
        "20,232475\n"          # activated seeded student -> Resolved
        "21,000000\n"          # no such user -> Unregistered ID
        "22,321321\n"          # exists but never signed in -> Unverified
    )

    token = await login(client, CONTROLLER_EMAIL)
    files = {"file": ("seatmap.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    resp = await client.post(f"/api/sessions/{SEEDED_SESSION_ID}/seatmap", headers=auth(token), files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    statuses = {row["seat_number"]: row["status"] for row in body["rows"]}
    assert statuses[20] == "Resolved"
    assert statuses[21] == "Unregistered ID"
    assert statuses[22] == "Unverified"
    assert body["resolved_count"] == 1
    assert body["rejected_count"] == 2

    rows_in_db = await admin_conn.fetch(
        "SELECT seat_number FROM seat_assignments WHERE session_id = $1 AND seat_number IN (20, 21, 22)",
        SEEDED_SESSION_ID,
    )
    assert {r["seat_number"] for r in rows_in_db} == {20}  # only the resolved row was written
