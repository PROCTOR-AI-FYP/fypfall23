"""Shared pytest fixtures.

Requires a real Postgres + Redis reachable at the DSNs in backend/.env (or
the defaults, which match backend/docker-compose.yml). Schema is
(re)applied once per test session; tables are truncated between tests so
each test starts from a clean, seeded state.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import db as db_module
from app import redis_client as redis_module
from app.config import settings
from app.main import app
from app.models import Role
from tests.helpers import CSRF_HEADERS

BACKEND_DIR = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres", "redis"}
ALLOW_REMOTE_ENV = "PROCTORAI_ALLOW_REMOTE_TEST_DB"
APP_TABLES = (
    "audit_log", "penalties", "cases", "detection_events", "seat_assignments", "exam_sessions", "users",
)


def _refuse_non_local_targets() -> None:
    """Every test TRUNCATEs all tables and FLUSHes Redis; never do that to a shared instance."""
    if os.environ.get(ALLOW_REMOTE_ENV) == "1":
        return
    for name, url in (("DATABASE_ADMIN_URL", settings.database_admin_url), ("REDIS_URL", settings.redis_url)):
        host = urlparse(url).hostname or ""
        if host not in LOCAL_HOSTS:
            pytest.exit(f"Refusing to run destructive tests against {name} host {host!r}. "
                        f"Point it at a local instance, or set {ALLOW_REMOTE_ENV}=1 for a disposable one.")


async def _apply_sql_file(conn: asyncpg.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    await conn.execute(sql)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_database() -> AsyncIterator[None]:
    _refuse_non_local_targets()
    admin_conn = await asyncpg.connect(dsn=settings.database_admin_url)
    try:
        await _apply_sql_file(admin_conn, BACKEND_DIR / "db" / "schema.sql")
    finally:
        await admin_conn.close()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    """Truncate all app tables and flush Redis before every test."""
    admin_conn = await asyncpg.connect(dsn=settings.database_admin_url)
    try:
        await admin_conn.execute(f"TRUNCATE {', '.join(APP_TABLES)} RESTART IDENTITY CASCADE")
        await _apply_sql_file(admin_conn, BACKEND_DIR / "db" / "seed.sql")
        # Seeded students count as having signed in once (seat maps only
        # resolve activated students). Staff stay un-activated so first-sign-in
        # linking can be tested. Never done in seed.sql itself: a made-up
        # identity on a real database would lock the real owner out.
        await admin_conn.execute(
            f"UPDATE users SET supabase_user_id = gen_random_uuid() WHERE role = '{Role.STUDENT.value}'"
        )
    finally:
        await admin_conn.close()

    redis_module.init_redis()
    await redis_module.get_redis().flushdb()

    yield


@pytest_asyncio.fixture
async def app_pool() -> AsyncIterator[asyncpg.Pool]:
    pool = await db_module.init_pool()
    yield pool
    await db_module.close_pool()


@pytest_asyncio.fixture
async def client(app_pool: asyncpg.Pool) -> AsyncIterator[AsyncClient]:
    redis_module.init_redis()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=CSRF_HEADERS) as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_conn() -> AsyncIterator[asyncpg.Connection]:
    """A superuser connection for asserting on DB state directly in tests."""
    conn = await asyncpg.connect(dsn=settings.database_admin_url)
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def low_priv_conn() -> AsyncIterator[asyncpg.Connection]:
    """A connection as the non-superuser app_user role, for proving RLS
    applies at the database level (not just in application code)."""
    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        yield conn
    finally:
        await conn.close()
