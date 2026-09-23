"""Diagnose app_user auth issue via admin connection."""
from __future__ import annotations
import asyncio, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import asyncpg
from dotenv import dotenv_values

PROJECT_REF = "vvjorsqsvkhpesbujbqt"
POOLER_HOST = "aws-0-ap-south-1.pooler.supabase.com"

async def main() -> None:
    v = dotenv_values(".env")
    admin_dsn = v["DATABASE_ADMIN_URL"]
    
    conn = await asyncio.wait_for(asyncpg.connect(dsn=admin_dsn), timeout=15)

    # Check app_user details
    row = await conn.fetchrow("""
        SELECT rolname, rolcanlogin, rolpassword IS NOT NULL as has_pw
        FROM pg_authid WHERE rolname = 'app_user'
    """)
    print(f"app_user in pg_authid: {dict(row) if row else 'NOT FOUND'}")

    app_password = v["APP_USER_PASSWORD"]
    print("\nResetting app_user password...")
    # ALTER ROLE takes no bind parameters; quote the literal server-side
    # instead of interpolating it into the SQL string.
    statement = await conn.fetchval("SELECT format('ALTER ROLE app_user PASSWORD %L', $1::text)", app_password)
    await conn.execute(statement)
    print("[OK] password reset done")

    # Also check if app_user can login
    can_login = await conn.fetchval("SELECT rolcanlogin FROM pg_authid WHERE rolname = 'app_user'")
    print(f"app_user rolcanlogin: {can_login}")

    await conn.close()
    print("\nNow test: try connecting as app_user.projectref with 'app_password'...")

    # Attempt connection as app_user via session pooler
    app_dsn = f"postgresql://app_user.{PROJECT_REF}:{app_password}@{POOLER_HOST}:5432/postgres"
    try:
        aconn = await asyncio.wait_for(asyncpg.connect(dsn=app_dsn), timeout=15)
        user = await aconn.fetchval("select current_user")
        await aconn.close()
        print(f"[OK] Connected as app_user: {user}")
    except Exception as e:
        print(f"[FAIL] {type(e).__name__}: {e}")

        # Try without project ref suffix
        app_dsn2 = f"postgresql://app_user:{app_password}@{POOLER_HOST}:5432/postgres"
        try:
            aconn2 = await asyncio.wait_for(asyncpg.connect(dsn=app_dsn2), timeout=15)
            user2 = await aconn2.fetchval("select current_user")
            await aconn2.close()
            print(f"[OK] Connected WITHOUT ref suffix as: {user2}")
        except Exception as e2:
            print(f"[FAIL] Without suffix: {type(e2).__name__}: {e2}")

asyncio.run(main())
