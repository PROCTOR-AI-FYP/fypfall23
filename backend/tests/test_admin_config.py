"""Classrooms, detection thresholds (and that the pipeline honours them),
the audit-log reader, statistics, and notifications."""
from __future__ import annotations

import asyncpg
import pytest
from httpx import AsyncClient

from app.models import BehaviourType
from app.services import detection
from tests.helpers import ADMIN_EMAIL, CONTROLLER_EMAIL, STUDENT_A_EMAIL, STUDENT_B_EMAIL, TEACHER_EMAIL, auth, login

SQUARE = [{"x": 10, "y": 10}, {"x": 60, "y": 10}, {"x": 60, "y": 60}, {"x": 10, "y": 60}]
DEFAULTS = [
    {"behaviour_type": "GAZE_DEVIATION", "sensitivity": 30, "weight": 0.2},
    {"behaviour_type": "HEAD_POSE_VIOLATION", "sensitivity": 30, "weight": 0.2},
    {"behaviour_type": "LIP_MOVEMENT", "sensitivity": 25, "weight": 0.15},
    {"behaviour_type": "PHONE_DETECTED", "sensitivity": 20, "weight": 0.25},
    {"behaviour_type": "UNAUTHORISED_OBJECT", "sensitivity": 20, "weight": 0.2},
]


async def test_classroom_crud_and_seat_map_validation(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    admin = auth(await login(client, ADMIN_EMAIL))
    created = await client.post("/api/admin/classrooms", headers=admin,
                                json={"name": "LH-9", "building": "Block C", "capacity": 36, "camera_status": "online"})
    assert created.status_code == 201, created.text
    room = created.json()
    assert room["seat_map"] is None
    assert (await client.post("/api/admin/classrooms", headers=admin,
                              json={"name": "LH-9", "building": "X", "capacity": 1})).status_code == 409

    bad_maps = [
        [{"seat_number": 1, "vertices": SQUARE[:2]}],                                        # fewer than 3 vertices
        [{"seat_number": 1, "vertices": SQUARE}, {"seat_number": 1, "vertices": SQUARE}],    # duplicate seat
        [{"seat_number": 0, "vertices": SQUARE}],                                            # seat out of range
        [{"seat_number": 1, "vertices": SQUARE, "label": "x"}],                              # unexpected field
    ]
    for seat_map in bad_maps:
        response = await client.patch(f"/api/admin/classrooms/{room['id']}", headers=admin, json={"seat_map": seat_map})
        assert response.status_code == 422, seat_map

    mapped = await client.patch(f"/api/admin/classrooms/{room['id']}", headers=admin,
                                json={"seat_map": [{"seat_number": 1, "vertices": SQUARE}, {"seat_number": 2, "vertices": SQUARE}]})
    assert mapped.status_code == 200 and len(mapped.json()["seat_map"]) == 2
    renamed = await client.patch(f"/api/admin/classrooms/{room['id']}", headers=admin, json={"camera_status": "maintenance"})
    assert renamed.json()["camera_status"] == "maintenance" and len(renamed.json()["seat_map"]) == 2  # map untouched
    staff_view = await client.get(f"/api/classrooms/{room['id']}", headers=auth(await login(client, TEACHER_EMAIL)))
    assert staff_view.status_code == 200 and staff_view.json()["name"] == "LH-9"

    assert (await client.delete("/api/admin/classrooms/00000000-0000-0000-0000-0000000c0001", headers=admin)).status_code == 409  # has sessions
    assert (await client.delete(f"/api/admin/classrooms/{room['id']}", headers=admin)).status_code == 204
    actions = [r["action"] for r in await admin_conn.fetch("SELECT action FROM audit_log WHERE action LIKE 'classroom_%' ORDER BY created_at")]
    assert actions == ["classroom_created", "classroom_updated", "classroom_updated", "classroom_deleted"]


async def test_thresholds_round_trip_and_validation(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    admin = auth(await login(client, ADMIN_EMAIL))
    current = (await client.get("/api/admin/thresholds", headers=admin)).json()
    assert [t["behaviour_type"] for t in current] == [b.value for b in BehaviourType]
    assert (await client.put("/api/admin/thresholds", headers=admin, json=DEFAULTS[:4])).status_code == 422
    assert (await client.put("/api/admin/thresholds", headers=admin, json=[*DEFAULTS[:4], DEFAULTS[0]])).status_code == 422
    out_of_range = [dict(DEFAULTS[0], sensitivity=101), *DEFAULTS[1:]]
    assert (await client.put("/api/admin/thresholds", headers=admin, json=out_of_range)).status_code == 422

    changed = [dict(t, sensitivity=45) if t["behaviour_type"] == "GAZE_DEVIATION" else t for t in DEFAULTS]
    saved = await client.put("/api/admin/thresholds", headers=admin, json=changed)
    assert saved.status_code == 200
    gaze = next(t for t in saved.json() if t["behaviour_type"] == "GAZE_DEVIATION")
    assert gaze["sensitivity"] == 45 and gaze["updated_by_name"] == "Admin Registrar"
    audit = await admin_conn.fetchval("SELECT new_value->'GAZE_DEVIATION' FROM audit_log WHERE action = 'thresholds_updated'")
    assert '"sensitivity": 45' in audit and '"previous": [30, 0.2]' in audit


@pytest.mark.parametrize(
    ("phone_sensitivity", "triggers"),
    [(20, True), (0, False)],  # 0.95 >= threshold 0.80 triggers; at sensitivity 0 the threshold is 1.0
)
async def test_detection_pipeline_uses_the_admin_thresholds(
    client: AsyncClient, admin_conn: asyncpg.Connection, phone_sensitivity: int, triggers: bool
) -> None:
    await admin_conn.execute("UPDATE detection_thresholds SET sensitivity = $1 WHERE behaviour_type = 'PHONE_DETECTED'", phone_sensitivity)
    detection.forget_detection_config()
    config = await detection.get_detection_config(admin_conn)
    windows = {(7, BehaviourType.PHONE_DETECTED): [0.95] * detection.BUFFER_WINDOW_FRAMES}
    assert bool(detection.evaluate_windows(windows, config)) is triggers


def test_weighted_composite() -> None:
    config = detection.DetectionConfig(weights={BehaviourType.PHONE_DETECTED: 0.25, BehaviourType.GAZE_DEVIATION: 0.2})
    single = config.composite({BehaviourType.PHONE_DETECTED: 0.9})
    both = config.composite({BehaviourType.PHONE_DETECTED: 0.9, BehaviourType.GAZE_DEVIATION: 0.72})
    assert single == 0.9 and both == round((0.9 * 0.25 + 0.72 * 0.2) / 0.45, 3)
    assert detection.DetectionConfig().composite({BehaviourType.PHONE_DETECTED: 0.4, BehaviourType.GAZE_DEVIATION: 0.7}) == 0.7


async def test_audit_log_reader_labels_and_filters(client: AsyncClient) -> None:
    admin = auth(await login(client, ADMIN_EMAIL))
    await client.post("/api/admin/users", headers=admin,
                      json={"full_name": "Hina Farooq", "email": "hina.farooq@students.au.edu.pk", "role": "teacher", "department": "Software Engineering"})
    await client.post("/api/auth/session", json={"supabase_access_token": "garbage"})
    entries = (await client.get("/api/admin/audit-log", headers=admin)).json()
    created = next(e for e in entries if e["action_code"] == "admin_create_user")
    assert created["action"] == "Created user" and created["user_name"] == "Admin Registrar" and created["user_role"] == "admin"
    assert "role: teacher" in created["details"]
    system = next(e for e in entries if e["action_code"] == "sign_in")
    assert system["user_name"] == "System" and system["user_role"] is None
    assert system["details"].startswith("outcome: invalid_token")

    by_label = (await client.get("/api/admin/audit-log", params={"action": "Created user"}, headers=admin)).json()
    by_code = (await client.get("/api/admin/audit-log", params={"action": "admin_create_user"}, headers=admin)).json()
    assert [e["id"] for e in by_label] == [e["id"] for e in by_code] == [created["id"]]


async def test_statistics_are_aggregates(client: AsyncClient) -> None:
    report = (await client.get("/api/reports/statistics", headers=auth(await login(client, CONTROLLER_EMAIL)))).json()
    assert report["total_cases"] == 2
    assert {s["label"]: s["count"] for s in report["case_status_distribution"]}["pending_review"] == 2
    assert report["incidents_by_department"] == [{"label": "Computer Science", "count": 2}]
    assert report["total_appeals"] == 0 and report["appeal_success_rate"] == 0.0
    assert [b["label"] for b in report["behavior_distribution"]] == [b.value for b in BehaviourType]


async def test_notifications_are_private(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    student_a = await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", STUDENT_A_EMAIL)
    note_id = await admin_conn.fetchval(
        "INSERT INTO notifications (user_id, type, title, message) VALUES ($1, 'system', 'Welcome', 'Hello') RETURNING id", student_a
    )
    a, b = auth(await login(client, STUDENT_A_EMAIL)), auth(await login(client, STUDENT_B_EMAIL))
    assert [n["title"] for n in (await client.get("/api/notifications", headers=a)).json()] == ["Welcome"]
    assert (await client.get("/api/notifications", headers=b)).json() == []
    assert (await client.post(f"/api/notifications/{note_id}/read", headers=b)).status_code == 404
    assert await admin_conn.fetchval("SELECT read_at FROM notifications WHERE id = $1", note_id) is None
    assert (await client.post(f"/api/notifications/{note_id}/read", headers=a)).status_code == 204
    assert (await client.get("/api/notifications", headers=a)).json()[0]["read"] is True
    assert (await client.post("/api/notifications/read-all", headers=b)).status_code == 204


async def test_rls_hides_other_users_notifications_at_the_database(
    admin_conn: asyncpg.Connection, low_priv_conn: asyncpg.Connection
) -> None:
    ids = [await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", e) for e in (STUDENT_A_EMAIL, STUDENT_B_EMAIL)]
    for user_id in ids:
        await admin_conn.execute("INSERT INTO notifications (user_id, type, title, message) VALUES ($1, 'system', 't', 'm')", user_id)
    async with low_priv_conn.transaction():
        await low_priv_conn.execute("SELECT set_config('app.current_user_id', $1, true)", str(ids[0]))
        await low_priv_conn.execute("SELECT set_config('app.current_role', 'hod', true)")  # even staff see only their own
        visible = await low_priv_conn.fetch("SELECT user_id FROM notifications")
        assert [r["user_id"] for r in visible] == [ids[0]]
        updated = await low_priv_conn.execute("UPDATE notifications SET read_at = now()")
        assert updated == "UPDATE 1"
