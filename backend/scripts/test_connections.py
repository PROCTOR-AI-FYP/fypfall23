"""Connection verification script - run once to confirm Supabase + Redis are reachable.

Usage:
    python scripts/test_connections.py

Reads .env from the current working directory (run from backend/).
"""
from __future__ import annotations

import asyncio
import sys

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import asyncpg
import redis.asyncio as redis_lib
from dotenv import dotenv_values


def _strip_quotes(s: str) -> str:
    return s.strip('"').strip("'")


async def try_pg(name: str, dsn: str) -> bool:
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn=dsn), timeout=15)
        user = await conn.fetchval("select current_user")
        version = await conn.fetchval("select version()")
        await conn.close()
        print(f"  [OK]   {name}")
        print(f"         connected as: {user}")
        print(f"         {version[:70]}")
        return True
    except Exception as exc:
        print(f"  [FAIL] {name}")
        print(f"         {type(exc).__name__}: {exc}")
        return False


async def try_redis(url: str) -> bool:
    clean_url = _strip_quotes(url)
    try:
        r = redis_lib.from_url(clean_url, decode_responses=True)
        await asyncio.wait_for(r.ping(), timeout=10)
        info = await r.info("server")
        await r.aclose()
        print(f"  [OK]   Redis")
        print(f"         redis_version={info.get('redis_version', '?')} "
              f"mode={info.get('redis_mode', '?')}")
        return True
    except Exception as exc:
        print(f"  [FAIL] Redis")
        print(f"         {type(exc).__name__}: {exc}")
        return False


async def main() -> None:
    v = dotenv_values(".env")

    # Session pooler - app_user (non-superuser, RLS applies)
    app_user_dsn = v.get("DATABASE_URL", "")
    # Session pooler - postgres superuser (for schema.sql / seed.sql only).
    admin_dsn = v.get("DATABASE_ADMIN_URL", "")

    redis_url = v.get("REDIS_URL", "")

    print("\n-- Supabase Postgres ------------------------------------------")
    ok1 = await try_pg("DATABASE_URL  (app_user, session pooler :5432)", app_user_dsn)
    ok2 = await try_pg("DATABASE_ADMIN_URL  (postgres, session pooler :5432)", admin_dsn)

    print("\n-- Upstash Redis ----------------------------------------------")
    ok3 = await try_redis(redis_url)

    print()
    if all([ok1, ok2, ok3]):
        print("All connections succeeded.")
    else:
        print("One or more connections FAILED - see details above.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
