"""asyncpg connection pool + Row-Level Security session-variable helper.

The pool connects as the non-superuser `app_user` Postgres role created in
db/schema.sql. That role is neither the owner of `cases` nor a superuser, so
the RLS policy defined on `cases` genuinely applies to it (Postgres exempts
superusers and table owners from RLS unless FORCE ROW LEVEL SECURITY is set,
which schema.sql also sets, belt-and-suspenders).

How the RLS session variable is populated from a JWT-authenticated request:
`deps.get_db_conn` (app/deps.py) is a FastAPI dependency that acquires a
connection from this pool, opens a transaction, and runs
`SELECT set_config('app.current_user_id', <uuid from JWT sub claim>, true)`
and `SELECT set_config('app.current_role', <role from JWT role claim>, true)`
before yielding the connection to the route handler. The `true` third
argument makes the setting transaction-local, so it can never leak across
pooled connections reused by other requests. The policy in db/schema.sql
reads these two settings via `current_setting(..., true)`.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=settings.db_pool_max_size,
            statement_cache_size=settings.db_statement_cache_size,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized; call init_pool() at startup.")
    return _pool


@asynccontextmanager
async def acquire_connection() -> AsyncIterator[asyncpg.Connection]:
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def acquire_rls_connection(*, user_id: str | None, role: str | None) -> AsyncIterator[asyncpg.Connection]:
    """Acquire a connection with the RLS session GUCs set for one transaction."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_user_id', $1, true)", user_id or "")
            await conn.execute("SELECT set_config('app.current_role', $1, true)", role or "")
            yield conn
