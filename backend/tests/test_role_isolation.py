"""Role isolation across all five roles, for every protected endpoint.

Each endpoint is called anonymously (must be 401) and as each role: roles not
allowed must get 403; allowed roles must get past the role gate (any status
other than 401/403: 200, or 404/409/422 for the deliberately empty or
unknown-id requests used here). Role dependencies run before body
validation, so empty bodies probe the gate without side effects.
Object ownership (a teacher's own sessions, a student's own cases) is covered
in test_case_lifecycle.py and test_scheduling.py.
"""
from __future__ import annotations

import re
import uuid

import asyncpg
import pytest
from httpx import AsyncClient

from tests.helpers import ADMIN_EMAIL, CONTROLLER_EMAIL, HOD_EMAIL, SEEDED_SESSION_ID, STUDENT_A_EMAIL, TEACHER_EMAIL, auth, login

ROLE_EMAILS = {
    "admin": ADMIN_EMAIL,
    "hod": HOD_EMAIL,
    "teacher": TEACHER_EMAIL,
    "exam_controller": CONTROLLER_EMAIL,
    "student": STUDENT_A_EMAIL,
}
ALL = set(ROLE_EMAILS)
STAFF = ALL - {"student"}
UNKNOWN = str(uuid.UUID(int=7))
CLASSROOM = "00000000-0000-0000-0000-0000000c0001"

# (method, path, allowed roles). {case}, {teacher} are filled in per test.
ENDPOINTS: list[tuple[str, str, set[str]]] = [
    ("GET", "/api/auth/me", ALL),
    ("GET", "/api/admin/users", {"admin", "exam_controller"}),
    ("POST", "/api/admin/users", {"admin"}),
    ("PATCH", "/api/admin/users/{teacher}", {"admin"}),
    ("DELETE", f"/api/admin/users/{UNKNOWN}", {"admin"}),
    ("GET", "/api/admin/audit-log", {"admin"}),
    ("GET", "/api/admin/thresholds", {"admin"}),
    ("PUT", "/api/admin/thresholds", {"admin"}),
    ("POST", "/api/admin/classrooms", {"admin"}),
    ("PATCH", f"/api/admin/classrooms/{UNKNOWN}", {"admin"}),
    ("DELETE", f"/api/admin/classrooms/{UNKNOWN}", {"admin"}),
    ("GET", "/api/classrooms", STAFF),
    ("GET", f"/api/classrooms/{CLASSROOM}", STAFF),
    ("GET", "/api/sessions", {"admin", "hod", "exam_controller", "teacher"}),
    ("GET", f"/api/sessions/{SEEDED_SESSION_ID}", {"admin", "hod", "exam_controller", "teacher"}),
    ("POST", "/api/sessions/start", {"teacher"}),
    ("POST", f"/api/sessions/{SEEDED_SESSION_ID}/end", {"admin", "exam_controller", "teacher"}),
    ("POST", f"/api/sessions/{SEEDED_SESSION_ID}/seatmap", {"admin", "exam_controller", "teacher"}),
    ("POST", "/api/seatmap/preview", {"admin", "exam_controller", "teacher"}),
    ("GET", "/api/exam-schedule", {"exam_controller", "admin"}),
    ("POST", "/api/exam-schedule", {"exam_controller", "admin"}),
    ("PATCH", f"/api/exam-schedule/{UNKNOWN}", {"exam_controller", "admin"}),
    ("DELETE", f"/api/exam-schedule/{UNKNOWN}", {"exam_controller", "admin"}),
    ("POST", f"/api/exam-schedule/{UNKNOWN}/invigilator", {"exam_controller", "admin"}),
    ("GET", "/api/invigilator-assignments", {"exam_controller", "admin"}),
    ("GET", "/api/detections", {"teacher", "hod"}),
    ("POST", f"/api/detections/{UNKNOWN}/confirm", {"teacher"}),
    ("POST", f"/api/detections/{UNKNOWN}/dismiss", {"teacher"}),
    ("GET", f"/api/detections/{UNKNOWN}/media", {"teacher", "hod"}),
    ("GET", "/api/cases", ALL),
    ("GET", "/api/cases/{case}", ALL),
    ("POST", "/api/cases/{case}/transitions", {"teacher", "hod"}),
    ("POST", "/api/cases/{case}/penalty", {"hod"}),
    ("GET", "/api/cases/{case}/penalty", {"hod"}),
    ("GET", "/api/cases/{case}/media", {"teacher", "hod"}),
    ("POST", "/api/cases/{case}/appeals", {"student"}),
    ("GET", "/api/appeals", {"hod", "student"}),
    ("GET", f"/api/appeals/{UNKNOWN}", {"hod", "student"}),
    ("POST", f"/api/appeals/{UNKNOWN}/resolve", {"hod"}),
    ("GET", "/api/notifications", ALL),
    ("POST", "/api/notifications/read-all", ALL),
    ("POST", f"/api/notifications/{UNKNOWN}/read", ALL),
    ("GET", "/api/reports/statistics", {"exam_controller", "admin", "hod"}),
]


@pytest.mark.parametrize(("method", "template", "allowed"), ENDPOINTS, ids=[f"{m} {p}" for m, p, _ in ENDPOINTS])
async def test_role_gate(
    client: AsyncClient, admin_conn: asyncpg.Connection, method: str, template: str, allowed: set[str]
) -> None:
    case_id = str(await admin_conn.fetchval("SELECT id FROM cases WHERE reference_no = 'AU-CS-INT-2026-014'"))
    teacher_id = str(await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", TEACHER_EMAIL))
    path = template.format(case=case_id, teacher=teacher_id)
    kwargs = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}

    anonymous = await client.request(method, path, **kwargs)
    assert anonymous.status_code == 401, f"anonymous {method} {path}: {anonymous.status_code}"

    failures = []
    for role, email in ROLE_EMAILS.items():
        response = await client.request(method, path, headers=auth(await login(client, email)), **kwargs)
        if role in allowed and response.status_code in (401, 403):
            failures.append(f"{role} should pass the gate, got {response.status_code}: {response.text[:120]}")
        if role not in allowed and response.status_code != 403:
            failures.append(f"{role} should be refused with 403, got {response.status_code}")
    assert not failures, f"{method} {path}:\n" + "\n".join(failures)


async def test_internal_endpoints_refuse_every_user_session(client: AsyncClient) -> None:
    """A signed-in user's cookie is no substitute for the worker's API key."""
    for email in ROLE_EMAILS.values():
        headers = auth(await login(client, email))
        for path in ("/internal/frames", "/internal/detections", f"/internal/cases/{UNKNOWN}/clip"):
            assert (await client.post(path, headers=headers, json={})).status_code == 401, (email, path)


async def test_every_protected_route_is_in_the_matrix() -> None:
    """New routes must be added above, so none ships without a role check."""
    from fastapi.routing import APIRoute

    from app.main import app

    def walk(routes, prefix=""):  # noqa: ANN001, ANN202
        for route in routes:
            if type(route).__name__ == "_IncludedRouter":
                yield from walk(route.original_router.routes, prefix + (getattr(route.include_context, "prefix", "") or ""))
            elif isinstance(route, APIRoute):
                for method in route.methods:
                    yield method, prefix + route.path

    def shape(path: str) -> str:
        path = re.sub(r"\{[^}]+\}", "{}", path)
        return re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "{}", path)

    covered = {(m, shape(p)) for m, p, _ in ENDPOINTS}
    public = {("POST", "/api/auth/session"), ("POST", "/api/auth/logout"), ("GET", "/healthz")}
    missing = [
        f"{method} {path}"
        for method, path in walk(app.routes)
        if not path.startswith("/internal") and (method, path) not in public and (method, shape(path)) not in covered
    ]
    assert not missing, missing
