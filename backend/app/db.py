"""asyncpg connection pool.

The pool connects as the non-superuser `app_user` Postgres role created in
db/schema.sql. That role owns no table and is not a superuser, so the RLS
policies in schema.sql genuinely apply to it (Postgres exempts superusers and
table owners from RLS unless FORCE ROW LEVEL SECURITY is set, which
schema.sql also sets, belt-and-suspenders).

The RLS session variables are set per request by deps.get_rls_db, from the
authenticated user as re-read from the users table: it opens a transaction
and runs `set_config('app.current_user_id', ..., true)` and
`set_config('app.current_role', ..., true)`. The `true` third argument makes
them transaction-local, so they never leak to the next request that reuses
the pooled connection. The policies read them via `current_setting(..., true)`.
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
