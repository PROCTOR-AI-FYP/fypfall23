"""Migration checklist: health check, CORS, production config gates, internal
API auth, proxy-aware client IPs, audit-log immutability, Supabase Data API
grants, Redis transport verification, and round-trip counts.
"""
from __future__ import annotations

import asyncpg
import pytest
import redis.asyncio.connection as redis_connection
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app import redis_client
from app.config import InsecureConfigurationError, Settings, settings, validate_settings
from app.main import cors_options
from tests.conftest import BACKEND_DIR, _apply_sql_file
from tests.helpers import INTERNAL_KEY, SEEDED_SESSION_ID

ALLOWED_ORIGIN = "https://proctorai.vercel.app"
PRODUCTION_BASE = {
    "app_env": "production",
    "cors_allowed_origins": ALLOWED_ORIGIN,
    "jwt_secret": "x" * 48,
    "internal_api_key": "y" * 48,
    "database_url": "postgresql://app_user.ref:strong-secret@pooler.supabase.com:5432/postgres",
    "redis_url": "rediss://default:token@example.upstash.io:6379",
    "require_redis_tls": True,
    "mqtt_enabled": True,
    "mqtt_use_tls": True,
    "mqtt_port": 8883,
    "trusted_proxy_hops": 1,
    "session_cookie_secure": True,
    "supabase_url": "https://project.supabase.co",
}


@pytest.fixture
def round_trips(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts every write to a Redis socket; a pipeline is a single write."""
    calls: list[int] = []
    original = redis_connection.AbstractConnection.send_packed_command

    async def counting(self, command, check_health=True):  # noqa: ANN001
        calls.append(1)
        return await original(self, command, check_health)

    monkeypatch.setattr(redis_connection.AbstractConnection, "send_packed_command", counting)
    return calls


async def test_healthz_requires_no_auth_and_leaks_nothing(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_cors_rejects_unlisted_origin_and_allows_configured_one() -> None:
    async def ok(_request):  # noqa: ANN001
        return PlainTextResponse("ok")

    probe = Starlette(
        routes=[Route("/api/cases", ok)],
        middleware=[Middleware(CORSMiddleware, **cors_options([ALLOWED_ORIGIN]))],
    )
    async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://test") as http:
        preflight_headers = {"Access-Control-Request-Method": "GET"}
        evil = await http.options("/api/cases", headers={"Origin": "https://evil.example", **preflight_headers})
        good = await http.options("/api/cases", headers={"Origin": ALLOWED_ORIGIN, **preflight_headers})
        evil_simple = await http.get("/api/cases", headers={"Origin": "https://proctorai-preview.vercel.app"})

    assert evil.status_code == 400
    assert "access-control-allow-origin" not in evil.headers
    assert good.status_code == 200
    assert good.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "access-control-allow-origin" not in evil_simple.headers


@pytest.mark.parametrize(
    "override",
    [
        {"cors_allowed_origins": "https://*.vercel.app"},
        {"cors_allowed_origins": ""},
        {"redis_url": "redis://default:token@example.upstash.io:6379"},
        {"require_redis_tls": False},
        {"mqtt_port": 1883},
        {"mqtt_use_tls": False},
        {"jwt_secret": "dev-only-jwt-secret-change-me-before-deploying"},
        {"jwt_secret": "short"},
        {"internal_api_key": ""},
        {"database_url": "postgresql://app_user:app_password@localhost:5432/proctorai"},
        {"trusted_proxy_hops": 0},
        {"session_cookie_secure": False},
        {"supabase_url": ""},
        {"supabase_url": "http://project.supabase.co"},
    ],
)
def test_production_refuses_insecure_configuration(override: dict[str, object]) -> None:
    with pytest.raises(InsecureConfigurationError):
        validate_settings(Settings(**{**PRODUCTION_BASE, **override}))


def test_production_accepts_secure_configuration() -> None:
    validate_settings(Settings(**PRODUCTION_BASE))


def test_wildcard_cors_rejected_even_in_development() -> None:
    with pytest.raises(InsecureConfigurationError):
        validate_settings(Settings(app_env="development", cors_allowed_origins="*"))


def test_samesite_none_cookie_requires_secure_everywhere() -> None:
    with pytest.raises(InsecureConfigurationError):
        validate_settings(Settings(app_env="development", session_cookie_samesite="none", session_cookie_secure=False))


async def test_internal_endpoints_reject_missing_wrong_or_unconfigured_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"session_id": SEEDED_SESSION_ID, "frame_index": 0, "seats": []}

    monkeypatch.setattr(settings, "internal_api_key", "")
    assert (await client.post("/internal/frames", json=body, headers={"X-Internal-Api-Key": ""})).status_code == 401

    monkeypatch.setattr(settings, "internal_api_key", INTERNAL_KEY)
    assert (await client.post("/internal/frames", json=body)).status_code == 401
    wrong = await client.post("/internal/frames", json=body, headers={"X-Internal-Api-Key": INTERNAL_KEY + "x"})
    assert wrong.status_code == 401
    assert (await client.post("/internal/detections", json={})).status_code == 401


async def test_spoofed_forwarded_for_cannot_forge_the_audited_ip(
    client: AsyncClient, admin_conn: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behind one proxy only the rightmost X-Forwarded-For entry is trustworthy."""
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    response = await client.post(
        "/api/auth/session",
        headers={"X-Forwarded-For": "10.0.0.9, 203.0.113.7"},
        json={"supabase_access_token": "not-a-jwt"},
    )
    assert response.status_code == 401
    assert await admin_conn.fetchval("SELECT ip_address FROM audit_log WHERE action = 'sign_in'") == "203.0.113.7"


async def test_audit_log_is_append_only(
    client: AsyncClient, admin_conn: asyncpg.Connection, low_priv_conn: asyncpg.Connection
) -> None:
    await client.post("/api/auth/session", json={"supabase_access_token": "not-a-jwt"})
    assert await admin_conn.fetchval("SELECT count(*) FROM audit_log") >= 1

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await low_priv_conn.execute("UPDATE audit_log SET action = 'tampered'")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await low_priv_conn.execute("DELETE FROM audit_log")
    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        await admin_conn.execute("UPDATE audit_log SET action = 'tampered'")
    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        await admin_conn.execute("DELETE FROM audit_log")


async def test_schema_strips_supabase_data_api_grants(admin_conn: asyncpg.Connection) -> None:
    """Simulate Supabase's default grants to anon/authenticated, then re-apply the schema."""
    for role in ("anon", "authenticated"):
        exists = await admin_conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
        if not exists:
            await admin_conn.execute(f'CREATE ROLE "{role}" NOLOGIN')
        await admin_conn.execute(f'GRANT ALL ON users, cases, audit_log, penalties TO "{role}"')

    await _apply_sql_file(admin_conn, BACKEND_DIR / "db" / "schema.sql")

    for role in ("anon", "authenticated"):
        for table in ("users", "cases", "audit_log", "penalties", "detection_events"):
            assert not await admin_conn.fetchval("SELECT has_table_privilege($1, $2, 'SELECT')", role, table)


async def test_plaintext_redis_is_detected_and_refused_when_tls_required(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert await redis_client.negotiated_tls_version(redis_client.get_redis()) is None
    monkeypatch.setattr(settings, "require_redis_tls", True)
    with pytest.raises(redis_client.InsecureRedisTransportError):
        await redis_client.verify_redis_transport()
