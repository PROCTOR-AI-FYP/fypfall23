"""Security checklist: seatmap upload never creates a seat_assignments row
for an unregistered registration number, or for a student account whose
owner has never signed in (activated) with Google.
"""
from __future__ import annotations

import io

import asyncpg
import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.helpers import CONTROLLER_EMAIL, SEEDED_SESSION_ID, auth, login

SCHEDULED_SESSION_ID = "00000000-0000-0000-0000-00000000d001"


@pytest_asyncio.fixture(autouse=True)
async def scheduled_session(admin_conn: asyncpg.Connection) -> str:
    await admin_conn.execute(
        "INSERT INTO exam_sessions (id, course_code, room, status) VALUES ($1, 'CS-2201', 'LH-4', 'scheduled')",
        SCHEDULED_SESSION_ID,
    )
    return SCHEDULED_SESSION_ID


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
    resp = await client.post(f"/api/sessions/{SCHEDULED_SESSION_ID}/seatmap", headers=auth(token), files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    statuses = {row["seat_number"]: row["status"] for row in body["rows"]}
    assert statuses[20] == "Resolved"
    assert statuses[21] == "Unregistered ID"
    assert statuses[22] == "Unverified"
    assert body["resolved_count"] == 1
    assert body["rejected_count"] == 2

    rows_in_db = await admin_conn.fetch("SELECT seat_number FROM seat_assignments WHERE session_id = $1", SCHEDULED_SESSION_ID)
    assert {r["seat_number"] for r in rows_in_db} == {20}  # only the resolved row was written
    assert await admin_conn.fetchval(
        "SELECT count(*) FROM audit_log WHERE action = 'seatmap_upload' AND target = $1", SCHEDULED_SESSION_ID
    ) == 1


def _csv(body: str) -> dict[str, tuple[str, io.BytesIO, str]]:
    return {"file": ("seatmap.csv", io.BytesIO(body.encode("utf-8")), "text/csv")}


async def test_reupload_replaces_the_whole_map(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    controller = auth(await login(client, CONTROLLER_EMAIL))
    url = f"/api/sessions/{SCHEDULED_SESSION_ID}/seatmap"
    assert (await client.post(url, headers=controller, files=_csv("seat_number,student_reg_no\n1,232475\n2,232490\n"))).status_code == 200
    assert (await client.post(url, headers=controller, files=_csv("seat_number,student_reg_no\n5,232475\n"))).status_code == 200
    seats = await admin_conn.fetch("SELECT seat_number FROM seat_assignments WHERE session_id = $1", SCHEDULED_SESSION_ID)
    assert [r["seat_number"] for r in seats] == [5]


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("seat,reg\n1,232475\n", "columns"),
        ("seat_number,student_reg_no\n", "empty"),
        ("seat_number,student_reg_no\n1,232475\n1,232490\n", "Seat number"),
        ("seat_number,student_reg_no\n1,232475\n2,232475\n", "more than once"),
    ],
)
async def test_malformed_files_are_rejected_without_writing(
    client: AsyncClient, admin_conn: asyncpg.Connection, body: str, fragment: str
) -> None:
    response = await client.post(
        f"/api/sessions/{SCHEDULED_SESSION_ID}/seatmap", headers=auth(await login(client, CONTROLLER_EMAIL)), files=_csv(body)
    )
    assert response.status_code == 422 and fragment in response.json()["detail"]
    assert await admin_conn.fetchval("SELECT count(*) FROM seat_assignments WHERE session_id = $1", SCHEDULED_SESSION_ID) == 0


async def test_non_utf8_oversized_and_bad_ids_are_client_errors(client: AsyncClient) -> None:
    controller = auth(await login(client, CONTROLLER_EMAIL))
    url = f"/api/sessions/{SCHEDULED_SESSION_ID}/seatmap"
    latin1 = {"file": ("s.csv", io.BytesIO("seat_number,student_reg_no\n1,Zo\xeb\n".encode("latin-1")), "text/csv")}
    assert (await client.post(url, headers=controller, files=latin1)).status_code == 422
    huge = {"file": ("s.csv", io.BytesIO(b"seat_number,student_reg_no\n" + b"1,232475\n" * 40000), "text/csv")}
    assert (await client.post(url, headers=controller, files=huge)).status_code == 413
    ok = _csv("seat_number,student_reg_no\n1,232475\n")
    assert (await client.post("/api/sessions/not-a-uuid/seatmap", headers=controller, files=ok)).status_code == 422


async def test_finished_exams_seat_maps_are_frozen(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/sessions/{SEEDED_SESSION_ID}/seatmap",
        headers=auth(await login(client, CONTROLLER_EMAIL)),
        files=_csv("seat_number,student_reg_no\n1,232475\n"),
    )
    assert response.status_code == 409
