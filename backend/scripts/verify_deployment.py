"""Live checks against the deployed backend and managed services.

Secrets are read from the environment, never from arguments (shell history):
  REDIS_URL, MQTT_HOST, MQTT_USERNAME, MQTT_PASSWORD, INTERNAL_API_KEY,
  E2E_SESSION_COOKIE (only with --e2e)

    python scripts/verify_deployment.py --base-url https://api.example.up.railway.app \\
        --allowed-origin https://proctorai.vercel.app
    # add the end-to-end detection check (creates one real case in the given session):
    python scripts/verify_deployment.py ... --e2e --session-id <in-progress session uuid> --room "Hall A"

Sign-in is Google-only, so --e2e borrows a real session: sign in to the
frontend as the session's invigilating teacher, copy the value of the
`proctorai_session` cookie (DevTools -> Application -> Cookies) into
E2E_SESSION_COOKIE. It expires with the session (JWT_EXPIRE_MINUTES).

Exit code is non-zero if any check fails.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import aiomqtt
import httpx
import redis.asyncio as redis
import socketio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.redis_client import negotiated_tls_version  # noqa: E402
from app.services.mqtt import alert_topic  # noqa: E402

FOREIGN_ORIGIN = "https://not-proctorai.example"
SESSION_COOKIE_NAME = "proctorai_session"
ALERT_EVENT = "alert:new"
MQTT_TIMEOUT_SECONDS = 10.0
EVENT_TIMEOUT_SECONDS = 15.0

results: list[tuple[str, bool, str]] = []


async def check(name: str, probe: Callable[[], Awaitable[str]]) -> None:
    try:
        evidence = await probe()
        results.append((name, True, evidence))
    except Exception as exc:  # noqa: BLE001 - every failure is reported, not raised
        results.append((name, False, f"{type(exc).__name__}: {exc}"))


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"environment variable {name} is not set")
    return value


async def healthz(base_url: str) -> str:
    async with httpx.AsyncClient(timeout=10) as http:
        response = await http.get(f"{base_url}/healthz")
    assert response.status_code == 200, f"status {response.status_code}"
    assert response.json() == {"status": "ok"}, f"body leaks more than status: {response.text!r}"
    assert "server" not in response.headers, f"server header present: {response.headers['server']}"
    return f"200 {response.text}"


async def cors(base_url: str, allowed_origin: str) -> str:
    headers = {"Access-Control-Request-Method": "GET"}
    async with httpx.AsyncClient(timeout=10) as http:
        foreign = await http.options(f"{base_url}/api/cases", headers={"Origin": FOREIGN_ORIGIN, **headers})
        allowed = await http.options(f"{base_url}/api/cases", headers={"Origin": allowed_origin, **headers})
    assert "access-control-allow-origin" not in foreign.headers, "foreign origin was allowed"
    assert allowed.headers.get("access-control-allow-origin") == allowed_origin, "configured origin not allowed"
    return f"foreign -> {foreign.status_code} without ACAO; {allowed_origin} -> ACAO echoed"


async def redis_tls() -> str:
    client = redis.from_url(require_env("REDIS_URL"))
    try:
        await client.ping()
        version = await negotiated_tls_version(client)
    finally:
        await client.aclose()
    assert version is not None, "connection is plaintext"
    return f"negotiated {version}"


async def mqtt_tls() -> str:
    async with aiomqtt.Client(
        hostname=require_env("MQTT_HOST"), port=8883, username=require_env("MQTT_USERNAME"),
        password=require_env("MQTT_PASSWORD"), tls_context=ssl.create_default_context(), timeout=MQTT_TIMEOUT_SECONDS,
    ) as client:
        sock = client._client.socket()
        assert isinstance(sock, ssl.SSLSocket), "not an SSL socket"
        return f"port 8883, {sock.version()}"


async def mqtt_plaintext_rejected() -> str:
    try:
        async with aiomqtt.Client(
            hostname=require_env("MQTT_HOST"), port=1883, username=require_env("MQTT_USERNAME"),
            password=require_env("MQTT_PASSWORD"), timeout=MQTT_TIMEOUT_SECONDS,
        ):
            pass
    except (aiomqtt.MqttError, OSError, TimeoutError) as exc:
        return f"plaintext 1883 refused ({type(exc).__name__})"
    raise AssertionError("plaintext connection on 1883 succeeded")


async def end_to_end(base_url: str, allowed_origin: str, session_id: str, room: str) -> str:
    cookie = {"Cookie": f"{SESSION_COOKIE_NAME}={require_env('E2E_SESSION_COOKIE')}"}
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as http:
        me = await http.get("/api/auth/me", headers=cookie)
        assert me.status_code == 200, f"session cookie rejected: {me.status_code}"
        assert me.json()["role"] == "teacher", f"session belongs to a {me.json()['role']}, not a teacher"

        sio = socketio.AsyncClient()
        socket_event: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        sio.on(ALERT_EVENT, lambda data: socket_event.done() or socket_event.set_result(data))
        # A browser sends its Origin on the handshake; the server checks it.
        await sio.connect(base_url, headers={**cookie, "Origin": allowed_origin}, transports=["websocket"])
        try:
            joined = await sio.call("join_session", {"session_id": session_id})
            assert joined == {"ok": True}, f"join_session: {joined}"

            async with aiomqtt.Client(
                hostname=require_env("MQTT_HOST"), port=8883, username=require_env("MQTT_USERNAME"),
                password=require_env("MQTT_PASSWORD"), tls_context=ssl.create_default_context(),
            ) as mqtt:
                topic = alert_topic(room)
                await mqtt.subscribe(topic, qos=1)
                detection = await http.post(
                    "/internal/detections",
                    headers={"X-Internal-Api-Key": require_env("INTERNAL_API_KEY")},
                    json={
                        "session_id": session_id, "seat_number": 999,
                        "behaviour_types": ["PHONE_DETECTED"], "per_signal": {"PHONE_DETECTED": 0.99},
                        "composite_score": 0.99, "snapshot_path": f"snapshots/{session_id}/verify-{uuid.uuid4().hex}.jpg",
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                assert detection.status_code == 201, f"detection: {detection.status_code} {detection.text}"
                reference = detection.json()["reference_no"]

                event = await asyncio.wait_for(socket_event, timeout=EVENT_TIMEOUT_SECONDS)
                assert event["reference_no"] == reference, "socket event for a different case"
                async with asyncio.timeout(EVENT_TIMEOUT_SECONDS):
                    async for message in mqtt.messages:
                        if json.loads(message.payload)["reference_no"] == reference:
                            break
        finally:
            await sio.disconnect()
    return f"case {reference}: Socket.IO event and MQTT message on {topic} received"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--allowed-origin", required=True)
    parser.add_argument("--e2e", action="store_true")
    parser.add_argument("--session-id")
    parser.add_argument("--room")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    await check("healthz is public and minimal", lambda: healthz(base_url))
    await check("CORS rejects foreign origins", lambda: cors(base_url, args.allowed_origin))
    await check("Redis connection is TLS", redis_tls)
    await check("MQTT connection is TLS on 8883", mqtt_tls)
    await check("MQTT plaintext 1883 is rejected", mqtt_plaintext_rejected)
    if args.e2e:
        if not (args.session_id and args.room):
            parser.error("--e2e needs --session-id and --room (and E2E_SESSION_COOKIE in the environment)")
        await check(
            "detection -> Socket.IO + MQTT",
            lambda: end_to_end(base_url, args.allowed_origin, args.session_id, args.room),
        )

    for name, ok, evidence in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {evidence}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    # paho-mqtt needs add_reader(), which Windows' default proactor loop lacks.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        sys.exit(runner.run(main()))
