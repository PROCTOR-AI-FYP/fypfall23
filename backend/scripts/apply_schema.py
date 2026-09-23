"""Apply schema.sql to Supabase via the admin (postgres) connection.

schema.sql owns every grant to app_user (least privilege: no UPDATE/DELETE
on audit_log, no DELETE on evidence tables). Do not add blanket
"GRANT ... ON ALL TABLES" here: that silently re-opens the audit log.

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
        print("[OK] schema.sql applied (including app_user grants).")

        can_tamper = await conn.fetchval(
            "SELECT has_table_privilege('app_user', 'audit_log', 'UPDATE')"
            " OR has_table_privilege('app_user', 'audit_log', 'DELETE')"
        )
        print("[FAIL] app_user can modify audit_log" if can_tamper else "[OK] audit_log is append-only for app_user.")

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
