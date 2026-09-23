"""Detection pipeline: pipelined buffers, triggering, cooldowns, detection ->
case -> Socket.IO + MQTT, and the MQTT outbox / heartbeat validation.
"""
from __future__ import annotations

import asyncio
import json
import re
import socket
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import aiomqtt
import asyncpg
import pytest
import pytest_asyncio
import socketio
import uvicorn
from httpx import AsyncClient

from app import sockets
from app.config import settings
from app.main import asgi_app
from app.models import BehaviourType
from app.redis_client import get_redis
from app.routers import internal
from app.services import detection, mqtt
from app.services.exam_sessions import clear_session_meta_cache
from tests.helpers import INTERNAL_KEY, STUDENT_A_EMAIL, TEACHER_EMAIL, login
from tests.test_infrastructure import round_trips  # noqa: F401  (fixture)

ACTIVE_SESSION_ID = "00000000-0000-0000-0000-00000000a001"
OTHER_SESSION_ID = "00000000-0000-0000-0000-00000000a002"
INTERNAL_HEADERS = {"X-Internal-Api-Key": INTERNAL_KEY}
REFERENCE_RE = re.compile(r"^AU-CS-INT-2026-\d{3,}$")


@pytest_asyncio.fixture
async def active_session(admin_conn: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch) -> str:
    """An in-progress session invigilated by the seeded teacher, with 232475 in seat 14."""
    monkeypatch.setattr(settings, "internal_api_key", INTERNAL_KEY)
    clear_session_meta_cache()
    await admin_conn.execute(
        """
        INSERT INTO exam_sessions (id, course_code, room, status, invigilator_id)
        SELECT $1, 'CS-3301', 'Hall B', 'in_progress', id FROM users WHERE email = $2
        """,
        ACTIVE_SESSION_ID,
        TEACHER_EMAIL,
    )
    await admin_conn.execute(
        "INSERT INTO exam_sessions (id, course_code, room, status) VALUES ($1, 'CS-3302', 'Hall C', 'in_progress')",
        OTHER_SESSION_ID,
    )
    await admin_conn.execute(
        """
        INSERT INTO seat_assignments (session_id, seat_number, student_reg_no, student_id)
        SELECT $1, 14, '232475', id FROM users WHERE registration_or_employee_no = '232475'
        """,
        ACTIVE_SESSION_ID,
    )
    yield ACTIVE_SESSION_ID
    clear_session_meta_cache()


def _detection_body(session_id: str, seat: int = 14) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "seat_number": seat,
        "behaviour_types": ["PHONE_DETECTED", "HEAD_POSE_VIOLATION"],
        "per_signal": {"PHONE_DETECTED": 0.91, "HEAD_POSE_VIOLATION": 0.68},
        "composite_score": 0.90,
        "snapshot_path": f"snapshots/{session_id}/{uuid.uuid4()}.jpg",
        "detected_at": datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc).isoformat(),
    }


async def test_frame_buffer_writes_are_one_round_trip_per_frame(
    client: AsyncClient, active_session: str, round_trips: list[int]  # noqa: F811
) -> None:
    seats = [
        detection.SeatSignals(seat_number=n, signals={signal: 0.1 for signal in BehaviourType})
        for n in range(1, 41)
    ]
    await detection.process_frame(active_session, frame_index=1, seats=seats)
    assert len(round_trips) == 1, "40 seats x 5 signals must go out as a single pipelined write"

    windows = await detection.record_frame(active_session, frame_index=2, seats=seats[:1])
    assert len(windows[(1, BehaviourType.GAZE_DEVIATION)]) == 2
    key = detection.buffer_key(active_session, 1, BehaviourType.GAZE_DEVIATION)
    assert await get_redis().llen(key) == 2


async def test_buffers_are_trimmed_to_the_window(client: AsyncClient, active_session: str) -> None:
    seat = [detection.SeatSignals(seat_number=3, signals={BehaviourType.GAZE_DEVIATION: 0.2})]
    for frame in range(detection.BUFFER_WINDOW_FRAMES + 7):
        await detection.record_frame(active_session, frame, seat)
    key = detection.buffer_key(active_session, 3, BehaviourType.GAZE_DEVIATION)
    assert await get_redis().llen(key) == detection.BUFFER_WINDOW_FRAMES
    assert await get_redis().ttl(key) > 0


async def test_frames_trigger_after_a_full_window_then_cool_down(client: AsyncClient, active_session: str) -> None:
    triggered_at = []
    for frame in range(detection.BUFFER_WINDOW_FRAMES + 2):
        response = await client.post(
            "/internal/frames",
            headers=INTERNAL_HEADERS,
            json={
                "session_id": active_session,
                "frame_index": frame,
                "seats": [
                    {"seat_number": 7, "signals": {"PHONE_DETECTED": 0.95, "GAZE_DEVIATION": 0.1}},
                    {"seat_number": 8, "signals": {"PHONE_DETECTED": 0.2}},
                ],
            },
        )
        assert response.status_code == 200, response.text
        if response.json()["triggered"]:
            triggered_at.append((frame, response.json()["triggered"]))

    assert len(triggered_at) == 1, "cooldown must suppress repeat alerts for the same seat"
    frame, seats = triggered_at[0]
    assert frame == detection.BUFFER_WINDOW_FRAMES - 1
    assert seats == [
        {"seat_number": 7, "behaviour_types": ["PHONE_DETECTED"], "per_signal": {"PHONE_DETECTED": 0.95},
         "composite_score": 0.95}
    ]
    assert await get_redis().ttl(detection.cooldown_key(active_session, 7)) > 0


async def test_lip_movement_ignored_outside_silent_exams(client: AsyncClient, active_session: str) -> None:
    for frame in range(detection.BUFFER_WINDOW_FRAMES):
        response = await client.post(
            "/internal/frames",
            headers=INTERNAL_HEADERS,
            json={"session_id": active_session, "frame_index": frame,
                  "seats": [{"seat_number": 5, "signals": {"LIP_MOVEMENT": 0.99}}]},
        )
        assert response.json()["triggered"] == []


async def test_frames_rejected_for_inactive_or_unknown_session(
    client: AsyncClient, active_session: str
) -> None:
    body = {"frame_index": 0, "seats": []}
    completed = await client.post(
        "/internal/frames", headers=INTERNAL_HEADERS,
        json={**body, "session_id": "00000000-0000-0000-0000-000000000001"},
    )
    unknown = await client.post("/internal/frames", headers=INTERNAL_HEADERS, json={**body, "session_id": str(uuid.uuid4())})
    assert completed.status_code == 409
    assert unknown.status_code == 404


async def test_detection_creates_linked_case_and_notifies_socket_and_mqtt(
    client: AsyncClient, active_session: str, admin_conn: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    emitted: list[tuple[str, dict[str, Any]]] = []
    published: list[tuple[str, dict[str, Any]]] = []

    async def fake_emit(session_id: str, payload: dict[str, Any]) -> None:
        emitted.append((session_id, payload))

    async def fake_publish(topic: str, payload: dict[str, Any]) -> bool:
        published.append((topic, payload))
        return True

    monkeypatch.setattr(internal, "emit_detection", fake_emit)
    monkeypatch.setattr(mqtt.mqtt_service, "publish", fake_publish)

    response = await client.post("/internal/detections", headers=INTERNAL_HEADERS, json=_detection_body(active_session))
    assert response.status_code == 201, response.text
    case = response.json()

    student_id = await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", STUDENT_A_EMAIL)
    assert case["student_id"] == str(student_id)
    assert case["status"] == "pending_review"
    assert REFERENCE_RE.match(case["reference_no"])
    assert await admin_conn.fetchval(
        "SELECT count(*) FROM detection_events de JOIN cases c ON c.detection_event_id = de.id WHERE c.id = $1",
        case["id"],
    ) == 1
    assert await admin_conn.fetchval(
        "SELECT count(*) FROM audit_log WHERE action = 'detection_recorded' AND target = $1", case["id"]
    ) == 1

    assert len(emitted) == 1
    assert emitted[0][0] == active_session
    assert emitted[0][1]["case_id"] == case["id"]
    assert published[0][0] == "proctorai/rooms/hall-b/alerts"
    assert "student_id" not in published[0][1]
    assert published[0][1]["reference_no"] == case["reference_no"]


async def test_unassigned_seat_creates_case_without_student(
    client: AsyncClient, active_session: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mqtt.mqtt_service, "publish", _noop_publish)
    response = await client.post(
        "/internal/detections", headers=INTERNAL_HEADERS, json=_detection_body(active_session, seat=40)
    )
    assert response.status_code == 201
    assert response.json()["student_id"] is None


async def _noop_publish(topic: str, payload: dict[str, Any]) -> bool:
    return True


@pytest.mark.parametrize(
    "snapshot_path",
    [
        f"snapshots/{OTHER_SESSION_ID}/frame.jpg",
        f"snapshots/{ACTIVE_SESSION_ID}/../{OTHER_SESSION_ID}/frame.jpg",
        f"snapshots/{ACTIVE_SESSION_ID}/frame.exe",
        "other-bucket/frame.jpg",
    ],
)
async def test_snapshot_path_must_stay_inside_the_session_folder(
    client: AsyncClient, active_session: str, snapshot_path: str
) -> None:
    body = {**_detection_body(active_session), "snapshot_path": snapshot_path}
    response = await client.post("/internal/detections", headers=INTERNAL_HEADERS, json=body)
    assert response.status_code == 422


def session_cookie(token: str) -> dict[str, str]:
    return {"Cookie": f"{settings.session_cookie_name}={token}"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest_asyncio.fixture
async def live_server(client: AsyncClient) -> AsyncIterator[str]:
    """The real ASGI app (FastAPI + Socket.IO) on a local port; pool and Redis come from `client`."""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(asgi_app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


async def test_end_to_end_detection_reaches_connected_socketio_client(
    client: AsyncClient, active_session: str, live_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mqtt.mqtt_service, "publish", _noop_publish)
    teacher_token = await login(client, TEACHER_EMAIL)
    student_token = await login(client, STUDENT_A_EMAIL)

    for rejected_headers in ({}, session_cookie("not-a-jwt"), session_cookie(student_token)):
        client_socket = socketio.AsyncClient()
        with pytest.raises(socketio.exceptions.ConnectionError):
            await client_socket.connect(live_server, headers=rejected_headers, transports=["websocket"])

    teacher = socketio.AsyncClient()
    received: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    teacher.on(sockets.EVENT_ALERT_NEW, received.put)
    await teacher.connect(live_server, headers=session_cookie(teacher_token), transports=["websocket"])
    try:
        assert await teacher.call(sockets.EVENT_JOIN_SESSION, {"session_id": OTHER_SESSION_ID}) == {
            "ok": False, "error": "forbidden"
        }
        assert await teacher.call(sockets.EVENT_JOIN_SESSION, {"session_id": active_session}) == {"ok": True}

        async with AsyncClient(base_url=live_server) as http:
            response = await http.post(
                "/internal/detections", headers=INTERNAL_HEADERS, json=_detection_body(active_session)
            )
        assert response.status_code == 201, response.text

        event = await asyncio.wait_for(received.get(), timeout=5)
        assert event["case_id"] == response.json()["id"]
        assert event["behaviour_types"] == ["PHONE_DETECTED", "HEAD_POSE_VIOLATION"]
    finally:
        await teacher.disconnect()


class _RecordingClient:
    def __init__(self, fail_on: int | None = None) -> None:
        self.published: list[tuple[str, str]] = []
        self._fail_on = fail_on

    async def publish(self, topic: str, payload: str, qos: int) -> None:
        if self._fail_on is not None and len(self.published) == self._fail_on:
            raise aiomqtt.MqttError("broker went away")
        self.published.append((topic, payload))


async def test_mqtt_publish_failure_queues_then_drains_in_order(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mqtt_enabled", True)
    service = mqtt.MqttService()
    service._client = _RecordingClient(fail_on=0)
    for n in range(3):
        assert await service.publish(f"proctorai/rooms/hall-b/alerts", {"n": n}) is False
    assert await get_redis().llen(mqtt.OUTBOX_KEY) == 3

    flaky = _RecordingClient(fail_on=1)
    with pytest.raises(aiomqtt.MqttError):
        await service._drain_outbox(flaky)
    assert [json.loads(p)["n"] for _, p in flaky.published] == [0]
    assert await get_redis().llen(mqtt.OUTBOX_KEY) == 2

    healthy = _RecordingClient()
    await service._drain_outbox(healthy)
    assert [json.loads(p)["n"] for _, p in healthy.published] == [1, 2]
    assert await get_redis().llen(mqtt.OUTBOX_KEY) == 0


async def test_mqtt_disabled_neither_publishes_nor_queues(client: AsyncClient) -> None:
    assert await mqtt.MqttService().publish("proctorai/rooms/x/alerts", {"n": 1}) is False
    assert await get_redis().llen(mqtt.OUTBOX_KEY) == 0


@pytest.mark.parametrize(
    ("topic", "payload", "accepted"),
    [
        ("proctorai/rooms/hall-b/heartbeat", b'{"device_id": "esp32-hall-b", "uptime_s": 42}', True),
        ("proctorai/rooms/hall-b/alerts", b'{"device_id": "esp32-hall-b", "uptime_s": 42}', False),
        ("proctorai/rooms/hall-b/heartbeat", b'{"device_id": "esp32", "uptime_s": 1, "cmd": "wipe"}', False),
        ("proctorai/rooms/hall-b/heartbeat", b'{"device_id": "x", "uptime_s": 1, "pad": "' + b"a" * 600 + b'"}', False),
        ("proctorai/rooms/hall-b/heartbeat", b"not json", False),
    ],
)
async def test_only_well_formed_heartbeats_are_accepted(
    client: AsyncClient, topic: str, payload: bytes, accepted: bool
) -> None:
    await mqtt.MqttService()._handle_message(topic, payload)
    assert (await get_redis().exists(mqtt.device_last_seen_key("hall-b")) == 1) is accepted


def test_room_slugs_are_topic_safe() -> None:
    assert mqtt.alert_topic("Hall B / East #2") == "proctorai/rooms/hall-b-east-2/alerts"
    assert mqtt.room_slug("+#") == "unassigned"
