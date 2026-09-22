"""Shared test helpers (seeded accounts all use the same password)."""
from __future__ import annotations

from httpx import AsyncClient

SEED_PASSWORD = "ChangeMe123!"
TEACHER_EMAIL = "m.bilal@students.au.edu.pk"
HOD_EMAIL = "hod.cs@students.au.edu.pk"
ADMIN_EMAIL = "admin.registrar@students.au.edu.pk"
CONTROLLER_EMAIL = "controller.exams@students.au.edu.pk"
STUDENT_A_EMAIL = "232475@students.au.edu.pk"
SEEDED_SESSION_ID = "00000000-0000-0000-0000-000000000001"
INTERNAL_KEY = "test-internal-key-0123456789abcdef0123"


async def login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
