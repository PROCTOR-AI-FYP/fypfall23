"""Case state machine with object-level authorization, penalty issuance with
exactly one Claude API call, and the snapshot purge job.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import asyncpg
import httpx2
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.config import settings
from app.services import notices, retention
from app.services.storage import SupabaseStorage
from tests.helpers import (
    ADMIN_EMAIL,
    HOD_EMAIL,
    SEEDED_SESSION_ID,
    STUDENT_A_EMAIL,
    TEACHER_EMAIL,
    auth,
    login,
)

OTHER_SESSION_ID = "00000000-0000-0000-0000-00000000b001"


async def _case_id(admin_conn: asyncpg.Connection, reference_no: str) -> str:
    return str(await admin_conn.fetchval("SELECT id FROM cases WHERE reference_no = $1", reference_no))


@pytest_asyncio.fixture
async def other_session_case(admin_conn: asyncpg.Connection) -> str:
    """A case in a session the seeded teacher does not invigilate."""
    await admin_conn.execute(
        "INSERT INTO exam_sessions (id, course_code, room, status) VALUES ($1, 'CS-2201', 'Hall D', 'completed')",
        OTHER_SESSION_ID,
    )
    return str(await admin_conn.fetchval(
        "INSERT INTO cases (session_id, seat_number, reference_no) VALUES ($1, 3, 'AU-CS-INT-2026-900') RETURNING id",
        OTHER_SESSION_ID,
    ))


async def _transition(client: AsyncClient, token: str, case_id: str, to_status: str) -> int:
    response = await client.post(
        f"/api/cases/{case_id}/transitions", headers=auth(token), json={"to_status": to_status, "note": "reviewed"}
    )
    return response.status_code


async def test_teacher_triages_own_session_case(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    case_id = await _case_id(admin_conn, "AU-CS-INT-2026-014")
    teacher = await login(client, TEACHER_EMAIL)

    assert await _transition(client, teacher, case_id, "escalated") == 200
    assert await admin_conn.fetchval("SELECT status FROM cases WHERE id = $1", case_id) == "escalated"
    audit = await admin_conn.fetchrow(
        "SELECT actor_id, new_value FROM audit_log WHERE action = 'case_transition' AND target = $1", case_id
    )
    assert audit is not None and '"to": "escalated"' in audit["new_value"]

    # Escalated cases belong to the HOD.
    assert await _transition(client, teacher, case_id, "dismissed") == 403
    hod = await login(client, HOD_EMAIL)
    assert await _transition(client, hod, case_id, "confirmed") == 200


async def test_teacher_cannot_see_or_touch_other_sessions(
    client: AsyncClient, other_session_case: str
) -> None:
    teacher = await login(client, TEACHER_EMAIL)
    assert await _transition(client, teacher, other_session_case, "confirmed") == 404
    listed = await client.get("/api/cases", headers=auth(teacher))
    assert other_session_case not in {case["id"] for case in listed.json()}


async def test_invalid_transitions_and_roles_are_rejected(client: AsyncClient, admin_conn: asyncpg.Connection) -> None:
    case_id = await _case_id(admin_conn, "AU-CS-INT-2026-014")
    hod = await login(client, HOD_EMAIL)
    assert await _transition(client, hod, case_id, "dismissed") == 200
    assert await _transition(client, hod, case_id, "confirmed") == 409  # dismissed is terminal

    for email in (STUDENT_A_EMAIL, ADMIN_EMAIL):
        token = await login(client, email)
        assert await _transition(client, token, case_id, "confirmed") == 403


def case_record_of(call: dict[str, Any]) -> dict[str, Any]:
    """The JSON case record inside the <case_record> block of a notice request."""
    content = call["messages"][0]["content"]
    return json.loads(content.split("<case_record>\n", 1)[1].split("\n</case_record>", 1)[0])


class _FakeMessages:
    """Stands in for client.beta.messages. Modes: ok (a faithful notice built
    from the record it was sent), connection_error, refusal, or any fixed text
    (to simulate a model that was talked into writing something else)."""

    def __init__(self, behaviour: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self._behaviour = behaviour

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self._behaviour == "connection_error":
            raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
        if self._behaviour == "ok":
            facts = case_record_of(kwargs)
            text = (
                "NOTICE OF ACADEMIC INTEGRITY DECISION\n"
                f"Reference: {facts['notice_reference']}\n"
                f"To: {facts['student_name']} (Registration No. {facts['student_reg_no']})\n"
                f"Course: {facts['course_code']}, {facts['room']}, {facts['exam_date']}\n"
                f"Penalty: {facts['penalty_type']}. {facts['penalty_description']}\n"
                "You may appeal through the ProctorAI portal."
            )
        else:
            text = self._behaviour
        return SimpleNamespace(
            stop_reason="refusal" if self._behaviour == "refusal" else "end_turn",
            content=[SimpleNamespace(type="text", text=text)],
            _request_id="req_test",
        )


@pytest.fixture
def fake_claude(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> _FakeMessages:
    messages = _FakeMessages(getattr(request, "param", "ok"))
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(notices, "_client", SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    return messages


async def _confirmed_case(client: AsyncClient, admin_conn: asyncpg.Connection) -> str:
    case_id = await _case_id(admin_conn, "AU-CS-INT-2026-014")
    assert await _transition(client, await login(client, HOD_EMAIL), case_id, "confirmed") == 200
    return case_id


async def test_penalty_generates_notice_with_exactly_one_api_call(
    client: AsyncClient, admin_conn: asyncpg.Connection, fake_claude: _FakeMessages
) -> None:
    case_id = await _confirmed_case(client, admin_conn)
    hod = await login(client, HOD_EMAIL)
    body = {"penalty_type": "formal_warning", "description": "A formal warning is placed on file."}

    issued = await client.post(f"/api/cases/{case_id}/penalty", headers=auth(hod), json=body)
    assert issued.status_code == 201, issued.text
    assert issued.json()["notice_source"] == "anthropic"
    assert issued.json()["notice_reference"] == "AU-CS-INT-2026-014"

    for _ in range(2):
        fetched = await client.get(f"/api/cases/{case_id}/penalty", headers=auth(hod))
        assert fetched.json()["notice_document"] == issued.json()["notice_document"]
    repeat = await client.post(f"/api/cases/{case_id}/penalty", headers=auth(hod), json=body)
    assert repeat.status_code == 409

    assert len(fake_claude.calls) == 1
    call = fake_claude.calls[0]
    assert call["model"] == settings.anthropic_model
    assert call["fallbacks"] == "default"
    assert "Ayesha Raza" in call["messages"][0]["content"]
    actions = await admin_conn.fetch(
        "SELECT action FROM audit_log WHERE action IN ('penalty_issued', 'notice_generated')"
    )
    assert sorted(row["action"] for row in actions) == ["notice_generated", "penalty_issued"]


@pytest.mark.parametrize("fake_claude", ["connection_error", "refusal"], indirect=True)
async def test_failed_generation_falls_back_to_template_without_retrying(
    client: AsyncClient, admin_conn: asyncpg.Connection, fake_claude: _FakeMessages
) -> None:
    case_id = await _confirmed_case(client, admin_conn)
    response = await client.post(
        f"/api/cases/{case_id}/penalty",
        headers=auth(await login(client, HOD_EMAIL)),
        json={"penalty_type": "mark_deduction", "description": "10% deducted from the final paper."},
    )
    assert response.status_code == 201
    assert response.json()["notice_source"] == "template"
    assert "AU-CS-INT-2026-014" in response.json()["notice_document"]
    assert "Ayesha Raza" in response.json()["notice_document"]
    assert len(fake_claude.calls) == 1


async def test_penalty_rules(client: AsyncClient, admin_conn: asyncpg.Connection, fake_claude: _FakeMessages) -> None:
    case_id = await _case_id(admin_conn, "AU-CS-INT-2026-014")
    body = {"penalty_type": "formal_warning", "description": "Warning."}
    hod = await login(client, HOD_EMAIL)
    assert (await client.post(f"/api/cases/{case_id}/penalty", headers=auth(hod), json=body)).status_code == 409
    teacher = await login(client, TEACHER_EMAIL)
    assert (await client.post(f"/api/cases/{case_id}/penalty", headers=auth(teacher), json=body)).status_code == 403
    assert fake_claude.calls == []


def test_claude_client_never_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(notices, "_client", None)
    assert notices._get_client().max_retries == 0


class _FakeStorage(SupabaseStorage):
    def __init__(self) -> None:
        super().__init__(base_url="https://example.supabase.co", service_role_key="key")
        self.deleted: list[list[str]] = []

    async def delete(self, paths: list[str]) -> None:
        self.deleted.append(paths)


async def test_purge_deletes_only_long_dismissed_snapshots(admin_conn: asyncpg.Connection) -> None:
    async def add_case(seat: int, status: str, age_days: int) -> str:
        detection_id = await admin_conn.fetchval(
            """
            INSERT INTO detection_events (session_id, seat_number, behaviour_types, per_signal, composite_score,
                                          snapshot_path, detected_at)
            VALUES ($1, $2, ARRAY['PHONE_DETECTED'], '{"PHONE_DETECTED": 0.9}', 0.9, $3, now())
            RETURNING id
            """,
            SEEDED_SESSION_ID, seat, f"snapshots/{SEEDED_SESSION_ID}/seat-{seat}.jpg",
        )
        await admin_conn.execute(
            """
            INSERT INTO cases (session_id, seat_number, reference_no, status, detection_event_id, updated_at)
            VALUES ($1, $2, $3, $4, $5, now() - make_interval(days => $6))
            """,
            SEEDED_SESSION_ID, seat, f"AU-CS-INT-2026-8{seat:02d}", status, detection_id, age_days,
        )
        return str(detection_id)

    old_dismissed = await add_case(21, "dismissed", settings.snapshot_retention_days + 5)
    await add_case(22, "dismissed", 1)
    await add_case(23, "confirmed", settings.snapshot_retention_days + 5)

    storage = _FakeStorage()
    assert await retention.purge_dismissed_evidence(admin_conn, storage) == 1
    assert storage.deleted == [[f"snapshots/{SEEDED_SESSION_ID}/seat-21.jpg"]]
    purged = await admin_conn.fetch("SELECT id FROM detection_events WHERE snapshot_purged_at IS NOT NULL")
    assert [str(row["id"]) for row in purged] == [old_dismissed]

    assert await retention.purge_dismissed_evidence(admin_conn, storage) == 0
    assert len(storage.deleted) == 1
