"""Exam scheduling, invigilator assignment, and starting/ending a session."""
from __future__ import annotations

from datetime import timedelta

import asyncpg
from httpx import AsyncClient

from app.services.clock import institution_today
from tests.helpers import ADMIN_EMAIL, CONTROLLER_EMAIL, HOD_EMAIL, TEACHER_EMAIL, auth, login

HALL_A = "00000000-0000-0000-0000-0000000c0001"
LH_4 = "00000000-0000-0000-0000-0000000c0002"


def _exam(**overrides: str) -> dict[str, str]:
    body = {
        "course_code": "cs-301", "course_name": "Database Systems", "department": "Computer Science",
        "date": institution_today().isoformat(), "start_time": "09:00", "end_time": "12:00", "classroom_id": HALL_A,
    }
    body.update(overrides)
    return body


async def _teacher_id(admin_conn: asyncpg.Connection, email: str = TEACHER_EMAIL) -> str:
    return str(await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", email))


async def test_schedule_validation_and_conflict_flags(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    controller = auth(await login(client, CONTROLLER_EMAIL))
    yesterday = (institution_today() - timedelta(days=1)).isoformat()
    assert (await client.post("/api/exam-schedule", headers=controller, json=_exam(date=yesterday))).status_code == 422
    assert (await client.post("/api/exam-schedule", headers=controller, json=_exam(end_time="08:00"))).status_code == 422
    assert (await client.post("/api/exam-schedule", headers=controller, json=_exam(classroom_id=LH_4[:-1] + "9"))).status_code == 422
    assert (await client.post("/api/exam-schedule", headers=controller, json=_exam(course_code="CS-301; DROP"))).status_code == 422

    first = await client.post("/api/exam-schedule", headers=controller, json=_exam())
    assert first.status_code == 201, first.text
    assert first.json()["course_code"] == "CS-301" and first.json()["classroom_name"] == "Hall-A"
    assert first.json()["has_conflict"] is False and first.json()["invigilator_id"] is None

    clash = (await client.post("/api/exam-schedule", headers=controller, json=_exam(course_code="SE-210", start_time="11:00", end_time="13:00"))).json()
    assert clash["has_conflict"] is True and "CS-301" in clash["conflict_details"]
    elsewhere = (await client.post("/api/exam-schedule", headers=controller, json=_exam(course_code="EE-110", classroom_id=LH_4))).json()
    assert elsewhere["has_conflict"] is False

    listed = {e["course_code"]: e for e in (await client.get("/api/exam-schedule", headers=controller)).json()}
    assert listed["CS-301"]["has_conflict"] is True  # both sides of a clash are flagged
    assert await admin_conn.fetchval("SELECT count(*) FROM audit_log WHERE action = 'exam_scheduled'") == 3

    cancelled = await client.delete(f"/api/exam-schedule/{clash['id']}", headers=controller)
    assert cancelled.status_code == 204
    assert "SE-210" not in {e["course_code"] for e in (await client.get("/api/exam-schedule", headers=controller)).json()}


async def test_invigilator_assignment(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    controller = auth(await login(client, CONTROLLER_EMAIL))
    teacher_id = await _teacher_id(admin_conn)
    hod_id = await _teacher_id(admin_conn, HOD_EMAIL)
    morning = (await client.post("/api/exam-schedule", headers=controller, json=_exam())).json()
    overlapping = (await client.post("/api/exam-schedule", headers=controller,
                                     json=_exam(course_code="SE-210", classroom_id=LH_4, start_time="10:00", end_time="11:00"))).json()

    assert (await client.post(f"/api/exam-schedule/{morning['id']}/invigilator", headers=controller,
                              json={"teacher_id": hod_id})).status_code == 422  # not a teacher
    assigned = await client.post(f"/api/exam-schedule/{morning['id']}/invigilator", headers=controller, json={"teacher_id": teacher_id})
    assert assigned.status_code == 200 and assigned.json()["teacher_name"] == "Dr. M. Bilal"
    double = await client.post(f"/api/exam-schedule/{overlapping['id']}/invigilator", headers=controller, json={"teacher_id": teacher_id})
    assert double.status_code == 409 and "already invigilating" in double.json()["detail"]

    assignments = (await client.get("/api/invigilator-assignments", headers=controller)).json()
    assert [(a["course_code"], a["teacher_id"]) for a in assignments] == [("CS-301", teacher_id)]
    teacher_inbox = (await client.get("/api/notifications", headers=auth(await login(client, TEACHER_EMAIL)))).json()
    assert any("CS-301" in n["title"] for n in teacher_inbox)


async def test_teacher_starts_only_their_own_exam_today(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    controller = auth(await login(client, CONTROLLER_EMAIL))
    teacher = auth(await login(client, TEACHER_EMAIL))
    start = {"classroom_id": HALL_A, "silent_mode": "false"}
    none_yet = await client.post("/api/sessions/start", headers=teacher, data=start)
    assert none_yet.status_code == 404 and "no exam scheduled" in none_yet.json()["detail"]

    exam = (await client.post("/api/exam-schedule", headers=controller, json=_exam())).json()
    unassigned = await client.post("/api/sessions/start", headers=teacher, data=start)
    assert unassigned.status_code == 404  # scheduled, but not their exam
    await client.post(f"/api/exam-schedule/{exam['id']}/invigilator", headers=controller, json={"teacher_id": await _teacher_id(admin_conn)})

    wrong_room = await client.post("/api/sessions/start", headers=teacher, data={**start, "classroom_id": LH_4})
    assert wrong_room.status_code == 404
    unresolved = await client.post("/api/sessions/start", headers=teacher, data=start,
                                   files={"file": ("s.csv", b"seat_number,student_reg_no\n1,232475\n2,999999\n", "text/csv")})
    assert unresolved.status_code == 409
    assert await admin_conn.fetchval("SELECT status FROM exam_sessions WHERE id = $1::uuid", exam["id"]) == "scheduled"

    started = await client.post("/api/sessions/start", headers=teacher, data=start)
    assert started.status_code == 200 and started.json()["status"] == "in_progress" and started.json()["started_at"]
    assert (await client.post("/api/sessions/start", headers=teacher, data=start)).status_code == 404  # nothing left to start
    # Scheduled exams that have started can no longer be edited, cancelled or reassigned.
    assert (await client.patch(f"/api/exam-schedule/{exam['id']}", headers=controller, json={"course_name": "X"})).status_code == 409
    assert (await client.delete(f"/api/exam-schedule/{exam['id']}", headers=controller)).status_code == 409


async def test_session_visibility_follows_invigilation(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    other_session = await admin_conn.fetchval(
        "INSERT INTO exam_sessions (course_code, room, status) VALUES ('ME-101', 'LH-7', 'scheduled') RETURNING id"
    )
    teacher = auth(await login(client, TEACHER_EMAIL))
    own = {s["id"] for s in (await client.get("/api/sessions", headers=teacher)).json()}
    assert str(other_session) not in own and "00000000-0000-0000-0000-000000000001" in own
    assert (await client.get(f"/api/sessions/{other_session}", headers=teacher)).status_code == 404
    assert (await client.post(f"/api/sessions/{other_session}/end", headers=teacher)).status_code == 404
    for email in (HOD_EMAIL, ADMIN_EMAIL, CONTROLLER_EMAIL):
        everyone = {s["id"] for s in (await client.get("/api/sessions", headers=auth(await login(client, email)))).json()}
        assert str(other_session) in everyone
    history = (await client.get("/api/sessions?status=completed", headers=auth(await login(client, CONTROLLER_EMAIL)))).json()
    assert [s["course_code"] for s in history] == ["CS-4402"]
    assert history[0]["classroom_name"] == "Hall-A" and history[0]["total_seats"] == 60 and history[0]["case_count"] == 2


async def test_preview_resolves_without_writing(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    preview = await client.post(
        "/api/seatmap/preview",
        headers=auth(await login(client, TEACHER_EMAIL)),
        files={"file": ("s.csv", b"seat_number,student_reg_no\n1,232475\n2,000000\n", "text/csv")},
    )
    assert preview.status_code == 200
    assert [r["status"] for r in preview.json()["rows"]] == ["Resolved", "Unregistered ID"]
    before = await admin_conn.fetchval("SELECT count(*) FROM seat_assignments")
    assert before == 2  # only the seed's rows
