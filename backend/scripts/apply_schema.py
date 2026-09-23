"""Apply schema.sql to Supabase via the admin (postgres) connection,
then create/update app_user with the correct password and update DATABASE_URL.

Usage:
    python scripts/apply_schema.py

Run from backend/ directory.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import asyncpg
from dotenv import dotenv_values

from dotenv import load_dotenv
load_dotenv()

PROJECT_REF = "vvjorsqsvkhpesbujbqt"
POOLER_HOST = "aws-0-ap-south-1.pooler.supabase.com"


async def main() -> None:
    v = dotenv_values(".env")
    admin_dsn = v["DATABASE_ADMIN_URL"]

    schema_path = Path("db/schema.sql")
    if not schema_path.exists():
        print("[FAIL] db/schema.sql not found. Run from backend/ directory.")
        sys.exit(1)

    schema_sql = schema_path.read_text(encoding="utf-8")

    print(f"Connecting to Supabase admin...")
    conn = await asyncio.wait_for(asyncpg.connect(dsn=admin_dsn), timeout=15)
    print("Connected.")

    try:
        # Apply schema
        print("\nApplying db/schema.sql ...")
        await conn.execute(schema_sql)
        print("[OK] schema.sql applied.")

        # Grant necessary privileges to app_user on all tables
        print("\nGranting privileges to app_user...")
        grant_sql = """
            GRANT USAGE ON SCHEMA public TO app_user;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
                GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
                GRANT USAGE, SELECT ON SEQUENCES TO app_user;
        """
        await conn.execute(grant_sql)
        print("[OK] Privileges granted.")

        # Verify app_user exists
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = 'app_user'"
        )
        if exists:
            print("\n[OK] app_user role exists in Supabase.")
        else:
            print("\n[FAIL] app_user role was NOT created. Check schema.sql output above.")

    finally:
        await conn.close()

    print("\nDone. Now test DATABASE_URL with app_user credentials.")


if __name__ == "__main__":
    asyncio.run(main())
