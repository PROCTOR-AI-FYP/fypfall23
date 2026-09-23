"""Shared test helpers.

Seeded accounts have no credentials (they sign in with Google in real use),
so `login` mints the app session JWT for a seeded account directly. The real
Google -> Supabase -> /api/auth/session exchange is exercised end to end with
signed test tokens in test_auth_session.py.
"""
from __future__ import annotations

from httpx import AsyncClient

from app import db as db_module
from app.config import settings
from app.csrf import CSRF_HEADER
from app.models import Role
from app.security import create_access_token

TEACHER_EMAIL = "m.bilal@students.au.edu.pk"
HOD_EMAIL = "hod.cs@students.au.edu.pk"
ADMIN_EMAIL = "admin.registrar@students.au.edu.pk"
CONTROLLER_EMAIL = "controller.exams@students.au.edu.pk"
STUDENT_A_EMAIL = "232475@students.au.edu.pk"
STUDENT_B_EMAIL = "232490@students.au.edu.pk"
SEEDED_SESSION_ID = "00000000-0000-0000-0000-000000000001"
INTERNAL_KEY = "test-internal-key-0123456789abcdef0123"
CSRF_HEADERS = {CSRF_HEADER: "1"}


async def login(client: AsyncClient, email: str) -> str:
    """Session token for an existing account, as /api/auth/session would issue it."""
    row = await db_module.get_pool().fetchrow("SELECT id, role FROM users WHERE email = $1", email)
    assert row is not None, f"no seeded user {email}"
    return create_access_token(user_id=str(row["id"]), role=Role(row["role"]))


def auth(token: str) -> dict[str, str]:
    """Headers a browser would send: the session cookie plus the CSRF header."""
    return {"Cookie": f"{settings.session_cookie_name}={token}", **CSRF_HEADERS}
