"""Audit logging helper — every auth attempt and every mutation is recorded.

audit_log is append-only at the database level (see db/schema.sql).
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

ACTION_SIGNUP_ATTEMPT = "signup_attempt"
ACTION_VERIFY_EMAIL_ATTEMPT = "verify_email_attempt"
ACTION_RESEND_VERIFICATION_ATTEMPT = "resend_verification_attempt"
ACTION_LOGIN_ATTEMPT = "login_attempt"
ACTION_ADMIN_CREATE_USER = "admin_create_user"
ACTION_SEATMAP_UPLOAD = "seatmap_upload"
ACTION_DETECTION_RECORDED = "detection_recorded"
ACTION_CASE_TRANSITION = "case_transition"
ACTION_PENALTY_ISSUED = "penalty_issued"
ACTION_NOTICE_GENERATED = "notice_generated"
ACTION_SNAPSHOTS_PURGED = "snapshots_purged"
ACTION_CLIP_STORED = "clip_stored"
ACTION_CLIPS_PURGED = "clips_purged"
ACTION_MEDIA_VIEWED = "evidence_media_viewed"


async def record_audit(
    conn: asyncpg.Connection,
    *,
    actor_id: str | None,
    action: str,
    target: str,
    new_value: dict[str, Any],
    ip_address: str | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO audit_log (actor_id, action, target, new_value, ip_address)
        VALUES ($1, $2, $3, $4::jsonb, $5)
        """,
        actor_id,
        action,
        target,
        json.dumps(new_value),
        ip_address,
    )
