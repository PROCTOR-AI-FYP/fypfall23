"""The academic-integrity workflow end to end, against the real API and a real
database: detection -> seat/student resolution -> invigilator triage -> HOD
decision and penalty -> notice -> student appeal -> HOD resolution.

Every legal and illegal case transition is exercised for both roles that can
act on cases; the other three roles are refused by role. The Claude API is
replaced by tests.test_case_workflow's fake (never called for real).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.config import settings
from app.services import mqtt
from app.services.clock import institution_today
from tests.helpers import (
    ADMIN_EMAIL,
    CONTROLLER_EMAIL,
    HOD_EMAIL,
    INTERNAL_KEY,
    STUDENT_A_EMAIL,
    STUDENT_B_EMAIL,
    TEACHER_EMAIL,
    auth,
    login,
)
from tests.test_case_workflow import _FakeMessages, fake_claude  # noqa: F401  (fixture)

INTERNAL = {"X-Internal-Api-Key": INTERNAL_KEY}
STATUSES = ["pending_review", "confirmed", "dismissed", "escalated"]
LIFECYCLE_SESSION = "00000000-0000-0000-0000-0000000e0001"
OTHER_SESSION = "00000000-0000-0000-0000-0000000e0002"


async def _noop_publish(topic: str, payload: dict[str, Any]) -> bool:
    return True


@pytest_asyncio.fixture
async def live_exam(admin_conn: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch) -> str:
    """Today's exam in Hall-A, invigilated by the seeded teacher, not yet started."""
    monkeypatch.setattr(settings, "internal_api_key", INTERNAL_KEY)
    monkeypatch.setattr(mqtt.mqtt_service, "publish", _noop_publish)
    await admin_conn.execute(
        """
        INSERT INTO exam_sessions (id, course_code, course_name, department, room, classroom_id, status,
                                   invigilator_id, scheduled_date, start_time, end_time)
        SELECT $1, 'CS-3301', 'Operating Systems', 'Computer Science', 'Hall-A',
               '00000000-0000-0000-0000-0000000c0001', 'scheduled', id, $2, TIME '09:00', TIME '12:00'
        FROM users WHERE email = $3
        """,
        LIFECYCLE_SESSION,
        institution_today(),
        TEACHER_EMAIL,
    )
    return LIFECYCLE_SESSION


async def _start_with_seats(client: AsyncClient, csv_body: str) -> dict[str, Any]:
    teacher = auth(await login(client, TEACHER_EMAIL))
    response = await client.post(
        "/api/sessions/start",
        headers=teacher,
        data={"classroom_id": "00000000-0000-0000-0000-0000000c0001", "silent_mode": "true"},
        files={"file": ("seats.csv", csv_body.encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _detection(session_id: str, seat: int, behaviours: dict[str, float] | None = None) -> dict[str, Any]:
    behaviours = behaviours or {"PHONE_DETECTED": 0.91, "HEAD_POSE_VIOLATION": 0.68}
    return {
        "session_id": session_id,
        "seat_number": seat,
        "behaviour_types": list(behaviours),
        "per_signal": behaviours,
        "composite_score": max(behaviours.values()),
        "snapshot_path": f"snapshots/{session_id}/{uuid.uuid4()}.jpg",
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }


# --- Detection -> seat and student ------------------------------------------


async def test_detection_resolves_seat_to_the_seated_student(
    client: AsyncClient, admin_conn: asyncpg.Connection, live_exam: str
) -> None:
    session = await _start_with_seats(client, "seat_number,student_reg_no\n14,232475\n15,232490\n")
    assert session["status"] == "in_progress" and session["silent_mode"] is True and session["occupied_seats"] == 2

    student_a = str(await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", STUDENT_A_EMAIL))
    student_b = str(await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", STUDENT_B_EMAIL))
    seat_14 = (await client.post("/internal/detections", headers=INTERNAL, json=_detection(live_exam, 14))).json()
    seat_15 = (await client.post("/internal/detections", headers=INTERNAL, json=_detection(live_exam, 15))).json()
    empty_seat = (await client.post("/internal/detections", headers=INTERNAL, json=_detection(live_exam, 30))).json()
    assert (seat_14["student_id"], seat_15["student_id"], empty_seat["student_id"]) == (student_a, student_b, None)
    assert seat_14["status"] == "pending_review" and seat_14["reference_no"].startswith("AU-CS-INT-")

    alerts = (await client.get(f"/api/detections?session_id={live_exam}", headers=auth(await login(client, TEACHER_EMAIL)))).json()
    by_seat = {a["seat_number"]: a for a in alerts}
    assert by_seat[14]["student_name"] == "Ayesha Raza" and by_seat[14]["status"] == "new"
    assert by_seat[30]["student_name"] is None


async def test_a_retried_detection_does_not_open_a_second_case(
    client: AsyncClient, admin_conn: asyncpg.Connection, live_exam: str
) -> None:
    await _start_with_seats(client, "seat_number,student_reg_no\n14,232475\n")
    body = _detection(live_exam, 14)
    assert (await client.post("/internal/detections", headers=INTERNAL, json=body)).status_code == 201
    assert (await client.post("/internal/detections", headers=INTERNAL, json=body)).status_code == 409
    assert await admin_conn.fetchval("SELECT count(*) FROM cases WHERE session_id = $1", live_exam) == 1


async def test_ending_the_exam_stops_detections_immediately(client: AsyncClient, live_exam: str) -> None:
    await _start_with_seats(client, "seat_number,student_reg_no\n14,232475\n")
    frame = {"session_id": live_exam, "frame_index": 0, "seats": []}
    assert (await client.post("/internal/frames", headers=INTERNAL, json=frame)).status_code == 200  # caches "in progress"
    ended = await client.post(f"/api/sessions/{live_exam}/end", headers=auth(await login(client, TEACHER_EMAIL)))
    assert ended.status_code == 200 and ended.json()["status"] == "completed"
    # No 30-second stale-cache window any more.
    assert (await client.post("/internal/frames", headers=INTERNAL, json=frame)).status_code == 409
    assert (await client.post("/internal/detections", headers=INTERNAL, json=_detection(live_exam, 14))).status_code == 409


# --- The full workflow --------------------------------------------------------


async def test_full_workflow_detection_to_resolved_appeal(
    client: AsyncClient, admin_conn: asyncpg.Connection, live_exam: str, fake_claude: _FakeMessages  # noqa: F811
) -> None:
    await _start_with_seats(client, "seat_number,student_reg_no\n14,232475\n")
    teacher, hod, student = [auth(await login(client, email)) for email in (TEACHER_EMAIL, HOD_EMAIL, STUDENT_A_EMAIL)]
    case = (await client.post("/internal/detections", headers=INTERNAL, json=_detection(live_exam, 14))).json()
    detection_id = str(await admin_conn.fetchval("SELECT detection_event_id FROM cases WHERE id = $1::uuid", case["id"]))

    # 1. The invigilator confirms the alert with a note; the case goes to the HOD, still pending.
    confirmed = await client.post(f"/api/detections/{detection_id}/confirm", headers=teacher,
                                  json={"teacher_note": "Phone visible under the desk for the whole window."})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "pending_review"
    assert confirmed.json()["teacher_note"].startswith("Phone visible")
    assert (await client.post(f"/api/detections/{detection_id}/confirm", headers=teacher, json={})).status_code == 409

    # 2. The HOD confirms and issues a penalty; exactly one (faked) Claude call drafts the notice.
    assert (await client.post(f"/api/cases/{case['id']}/transitions", headers=hod, json={"to_status": "confirmed"})).status_code == 200
    penalty = await client.post(f"/api/cases/{case['id']}/penalty", headers=hod,
                                json={"penalty_type": "mark_deduction", "description": "20% deducted from the final paper."})
    assert penalty.status_code == 201, penalty.text
    assert penalty.json()["notice_source"] == "anthropic" and penalty.json()["issued_by_name"] == "Dr. Sara Khan"
    assert len(fake_claude.calls) == 1

    # 3. The student sees their case with the penalty, but not the invigilator's note or the staff timeline.
    own = (await client.get(f"/api/cases/{case['id']}", headers=student)).json()
    assert own["penalty"]["penalty_type"] == "mark_deduction"
    assert own["teacher_note"] is None and own["teacher_name"] is None and own["timeline"] == []
    assert any(n["type"] == "penalty" for n in (await client.get("/api/notifications", headers=student)).json())

    # 4. The student appeals; a second appeal while one is open is refused.
    appeal = await client.post(f"/api/cases/{case['id']}/appeals", headers=student,
                               json={"statement": "The phone was switched off and in my bag.", "supporting_info": "https://drive.example/receipt"})
    assert appeal.status_code == 201, appeal.text
    assert appeal.json()["status"] == "open" and appeal.json()["case_reference_no"] == case["reference_no"]
    duplicate = await client.post(f"/api/cases/{case['id']}/appeals", headers=student, json={"statement": "Again."})
    assert duplicate.status_code == 409

    # 5. The HOD accepts: the case is dismissed and the penalty withdrawn.
    resolved = await client.post(f"/api/appeals/{appeal.json()['id']}/resolve", headers=hod,
                                 json={"status": "accepted", "review_note": "Bag search confirmed the phone was off."})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "accepted" and resolved.json()["reviewer_name"] == "Dr. Sara Khan"
    final = (await client.get(f"/api/cases/{case['id']}", headers=hod)).json()
    assert final["status"] == "dismissed" and final["penalty"]["revoked_at"] is not None
    assert (await client.post(f"/api/appeals/{appeal.json()['id']}/resolve", headers=hod,
                              json={"status": "rejected", "review_note": "Changed my mind."})).status_code == 409

    # 6. The timeline is the audit trail, in order.
    assert [entry["action"] for entry in final["timeline"]] == [
        "Detection recorded",
        "Confirmed as case by invigilator",
        "Case confirmed",
        "Penalty issued: Mark Deduction",
        "Notice generated",
        "Appeal submitted",
        "Case dismissed on appeal",
        "Appeal accepted",
    ]
    student_view = (await client.get(f"/api/cases/{case['id']}", headers=student)).json()
    assert student_view["appeal"]["review_note"] == "Bag search confirmed the phone was off."
    assert any(n["type"] == "appeal" for n in (await client.get("/api/notifications", headers=student)).json())


async def test_teacher_dismissal_from_the_alert_inbox(
    client: AsyncClient, admin_conn: asyncpg.Connection, live_exam: str
) -> None:
    await _start_with_seats(client, "seat_number,student_reg_no\n14,232475\n")
    case = (await client.post("/internal/detections", headers=INTERNAL, json=_detection(live_exam, 14))).json()
    detection_id = str(await admin_conn.fetchval("SELECT detection_event_id FROM cases WHERE id = $1::uuid", case["id"]))
    teacher = auth(await login(client, TEACHER_EMAIL))
    dismissed = await client.post(f"/api/detections/{detection_id}/dismiss", headers=teacher, json={"note": "Student was stretching."})
    assert dismissed.status_code == 200 and dismissed.json()["status"] == "dismissed"
    assert await admin_conn.fetchval("SELECT status FROM cases WHERE id = $1::uuid", case["id"]) == "dismissed"
    # Nothing leaves dismissed.
    assert (await client.post(f"/api/detections/{detection_id}/dismiss", headers=teacher, json={})).status_code == 409
    assert (await client.post(f"/api/detections/{detection_id}/confirm", headers=teacher, json={})).status_code == 409


# --- Every transition ---------------------------------------------------------


@pytest_asyncio.fixture
async def case_in(admin_conn: asyncpg.Connection):  # noqa: ANN201
    """Factory: a case in a given status, in a session the seeded teacher invigilates."""
    async def make(status_value: str, *, session_id: str = "00000000-0000-0000-0000-000000000001") -> str:
        return str(await admin_conn.fetchval(
            """
            INSERT INTO cases (session_id, seat_number, student_id, reference_no, status)
            SELECT $1::uuid, 20, id, 'AU-CS-INT-2026-' || nextval('case_reference_seq'), $2
            FROM users WHERE email = $3
            RETURNING id
            """,
            session_id, status_value, STUDENT_A_EMAIL,
        ))
    return make


def _expected(role: str, current: str, target: str) -> int:
    legal = {
        "pending_review": {"confirmed", "dismissed", "escalated"},
        "escalated": {"confirmed", "dismissed"},
        "confirmed": set(),
        "dismissed": set(),
    }
    if target not in legal[current]:
        return 409
    if role == "teacher" and current == "escalated":
        return 403  # escalated cases are the HOD's decision
    return 200


@pytest.mark.parametrize("role_email", [TEACHER_EMAIL, HOD_EMAIL], ids=["teacher", "hod"])
@pytest.mark.parametrize("current", STATUSES)
@pytest.mark.parametrize("target", STATUSES)
async def test_every_transition(
    client: AsyncClient, admin_conn: asyncpg.Connection, case_in, role_email: str, current: str, target: str  # noqa: ANN001
) -> None:
    case_id = await case_in(current)
    response = await client.post(
        f"/api/cases/{case_id}/transitions",
        headers=auth(await login(client, role_email)),
        json={"to_status": target, "note": "matrix"},
    )
    role = "teacher" if role_email == TEACHER_EMAIL else "hod"
    assert response.status_code == _expected(role, current, target), response.text
    stored = await admin_conn.fetchval("SELECT status FROM cases WHERE id = $1::uuid", case_id)
    audited = await admin_conn.fetchval("SELECT count(*) FROM audit_log WHERE action = 'case_transition' AND target = $1", case_id)
    if response.status_code == 200:
        assert stored == target and audited == 1
    else:
        assert stored == current and audited == 0  # refused transitions change nothing and log nothing


@pytest.mark.parametrize("email", [ADMIN_EMAIL, CONTROLLER_EMAIL, STUDENT_A_EMAIL])
async def test_non_reviewer_roles_cannot_transition(client: AsyncClient, case_in, email: str) -> None:  # noqa: ANN001
    case_id = await case_in("pending_review")
    response = await client.post(f"/api/cases/{case_id}/transitions", headers=auth(await login(client, email)),
                                 json={"to_status": "dismissed"})
    assert response.status_code == 403


async def test_teacher_cannot_transition_cases_outside_their_sessions(
    client: AsyncClient, admin_conn: asyncpg.Connection, case_in  # noqa: ANN001
) -> None:
    await admin_conn.execute("INSERT INTO exam_sessions (id, course_code, room, status) VALUES ($1, 'CS-9999', 'LH-7', 'completed')", OTHER_SESSION)
    case_id = await case_in("pending_review", session_id=OTHER_SESSION)
    teacher = auth(await login(client, TEACHER_EMAIL))
    assert (await client.post(f"/api/cases/{case_id}/transitions", headers=teacher, json={"to_status": "dismissed"})).status_code == 404
    assert (await client.get(f"/api/cases/{case_id}", headers=teacher)).status_code == 404


# --- Penalties require a confirmed case ---------------------------------------


@pytest.mark.parametrize("current", ["pending_review", "escalated", "dismissed"])
async def test_penalty_requires_confirmed(
    client: AsyncClient, admin_conn: asyncpg.Connection, case_in, fake_claude: _FakeMessages, current: str  # noqa: ANN001, F811
) -> None:
    case_id = await case_in(current)
    response = await client.post(f"/api/cases/{case_id}/penalty", headers=auth(await login(client, HOD_EMAIL)),
                                 json={"penalty_type": "formal_warning", "description": "Warning."})
    assert response.status_code == 409
    assert await admin_conn.fetchval("SELECT count(*) FROM penalties WHERE case_id = $1::uuid", case_id) == 0
    assert fake_claude.calls == []


async def test_one_penalty_per_confirmed_case(
    client: AsyncClient, case_in, fake_claude: _FakeMessages  # noqa: ANN001, F811
) -> None:
    case_id = await case_in("confirmed")
    hod = auth(await login(client, HOD_EMAIL))
    body = {"penalty_type": "exam_voidance", "description": "The paper is void."}
    assert (await client.post(f"/api/cases/{case_id}/penalty", headers=hod, json=body)).status_code == 201
    assert (await client.post(f"/api/cases/{case_id}/penalty", headers=hod, json=body)).status_code == 409
    assert len(fake_claude.calls) == 1


# --- Appeal rules ----------------------------------------------------------------


@pytest_asyncio.fixture
async def penalised_case(client: AsyncClient, case_in, fake_claude: _FakeMessages) -> str:  # noqa: ANN001, F811
    case_id = await case_in("confirmed")
    response = await client.post(f"/api/cases/{case_id}/penalty", headers=auth(await login(client, HOD_EMAIL)),
                                 json={"penalty_type": "formal_warning", "description": "A formal warning is placed on file."})
    assert response.status_code == 201
    return case_id


async def test_appeal_preconditions(client: AsyncClient, case_in) -> None:  # noqa: ANN001
    student = auth(await login(client, STUDENT_A_EMAIL))
    body = {"statement": "I was not cheating."}
    for status_value in ("pending_review", "escalated", "dismissed", "confirmed"):  # none has a penalty
        case_id = await case_in(status_value)
        assert (await client.post(f"/api/cases/{case_id}/appeals", headers=student, json=body)).status_code == 409, status_value


async def test_only_the_accused_student_can_appeal(client: AsyncClient, penalised_case: str) -> None:
    body = {"statement": "Not me."}
    other_student = await client.post(f"/api/cases/{penalised_case}/appeals", headers=auth(await login(client, STUDENT_B_EMAIL)), json=body)
    assert other_student.status_code == 404  # RLS: the case does not exist for them
    for email in (TEACHER_EMAIL, HOD_EMAIL, ADMIN_EMAIL, CONTROLLER_EMAIL):
        assert (await client.post(f"/api/cases/{penalised_case}/appeals", headers=auth(await login(client, email)), json=body)).status_code == 403


async def test_appeal_window_and_validation(
    client: AsyncClient, admin_conn: asyncpg.Connection, penalised_case: str
) -> None:
    student = auth(await login(client, STUDENT_A_EMAIL))
    assert (await client.post(f"/api/cases/{penalised_case}/appeals", headers=student, json={"statement": "   "})).status_code == 422
    assert (await client.post(f"/api/cases/{penalised_case}/appeals", headers=student, json={"statement": "x" * 5001})).status_code == 422
    await admin_conn.execute(
        "UPDATE penalties SET created_at = now() - make_interval(days => $2) WHERE case_id = $1::uuid",
        penalised_case, settings.appeal_window_days + 1,
    )
    closed = await client.post(f"/api/cases/{penalised_case}/appeals", headers=student, json={"statement": "Too late?"})
    assert closed.status_code == 409 and "window" in closed.json()["detail"]


async def test_rejected_appeal_is_final_and_leaves_the_penalty(
    client: AsyncClient, admin_conn: asyncpg.Connection, penalised_case: str
) -> None:
    student, hod = auth(await login(client, STUDENT_A_EMAIL)), auth(await login(client, HOD_EMAIL))
    appeal = (await client.post(f"/api/cases/{penalised_case}/appeals", headers=student, json={"statement": "Please review."})).json()
    for email in (TEACHER_EMAIL, STUDENT_A_EMAIL, ADMIN_EMAIL, CONTROLLER_EMAIL):
        forbidden = await client.post(f"/api/appeals/{appeal['id']}/resolve", headers=auth(await login(client, email)),
                                      json={"status": "accepted", "review_note": "ok"})
        assert forbidden.status_code == 403, email
    assert (await client.post(f"/api/appeals/{appeal['id']}/resolve", headers=hod, json={"status": "open", "review_note": "?"})).status_code == 422
    assert (await client.post(f"/api/appeals/{appeal['id']}/resolve", headers=hod, json={"status": "rejected", "review_note": " "})).status_code == 422

    rejected = await client.post(f"/api/appeals/{appeal['id']}/resolve", headers=hod,
                                 json={"status": "rejected", "review_note": "The recording is unambiguous."})
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert await admin_conn.fetchval("SELECT status FROM cases WHERE id = $1::uuid", penalised_case) == "confirmed"
    assert await admin_conn.fetchval("SELECT revoked_at FROM penalties WHERE case_id = $1::uuid", penalised_case) is None
    again = await client.post(f"/api/cases/{penalised_case}/appeals", headers=student, json={"statement": "One more time."})
    assert again.status_code == 409 and "final" in again.json()["detail"]


async def test_one_open_appeal_is_enforced_by_the_database(
    admin_conn: asyncpg.Connection, penalised_case: str
) -> None:
    student_id = await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", STUDENT_A_EMAIL)
    insert = "INSERT INTO appeals (case_id, student_id, statement) VALUES ($1::uuid, $2, 'x')"
    await admin_conn.execute(insert, penalised_case, student_id)
    with pytest.raises(asyncpg.UniqueViolationError):
        await admin_conn.execute(insert, penalised_case, student_id)


async def test_students_only_ever_see_their_own_appeals(client: AsyncClient, penalised_case: str) -> None:
    appeal = (await client.post(f"/api/cases/{penalised_case}/appeals", headers=auth(await login(client, STUDENT_A_EMAIL)),
                                json={"statement": "Mine."})).json()
    student_b = auth(await login(client, STUDENT_B_EMAIL))
    assert (await client.get(f"/api/appeals/{appeal['id']}", headers=student_b)).status_code == 404
    assert (await client.get("/api/appeals", headers=student_b)).json() == []
    assert (await client.get(f"/api/cases/{penalised_case}", headers=student_b)).status_code == 404
    hod_list = (await client.get("/api/appeals?status=open", headers=auth(await login(client, HOD_EMAIL)))).json()
    assert [a["id"] for a in hod_list] == [appeal["id"]]
