"""Audit logging helper — every auth attempt and every mutation is recorded.

audit_log is append-only at the database level (see db/schema.sql).
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

ACTION_SIGN_IN = "sign_in"
# Recorded separately from ACTION_SIGN_IN so it stands out in the audit log:
# a verified Google identity tried to use an account already linked to a
# different one.
ACTION_SECURITY_RELINK_REJECTED = "security_relink_rejected"
ACTION_SIGN_OUT = "sign_out"
ACTION_ADMIN_CREATE_USER = "admin_create_user"
ACTION_ADMIN_UPDATE_USER = "admin_update_user"
ACTION_ADMIN_DELETE_USER = "admin_delete_user"
ACTION_SEATMAP_UPLOAD = "seatmap_upload"
ACTION_DETECTION_RECORDED = "detection_recorded"
ACTION_ALERT_CONFIRMED = "alert_confirmed"
ACTION_CASE_TRANSITION = "case_transition"
ACTION_PENALTY_ISSUED = "penalty_issued"
ACTION_NOTICE_GENERATED = "notice_generated"
ACTION_APPEAL_SUBMITTED = "appeal_submitted"
ACTION_APPEAL_RESOLVED = "appeal_resolved"
ACTION_SNAPSHOTS_PURGED = "snapshots_purged"
ACTION_CLIP_STORED = "clip_stored"
ACTION_CLIPS_PURGED = "clips_purged"
ACTION_MEDIA_VIEWED = "evidence_media_viewed"
ACTION_SESSION_STARTED = "session_started"
ACTION_SESSION_ENDED = "session_ended"
ACTION_EXAM_SCHEDULED = "exam_scheduled"
ACTION_EXAM_UPDATED = "exam_updated"
ACTION_EXAM_CANCELLED = "exam_cancelled"
ACTION_INVIGILATOR_ASSIGNED = "invigilator_assigned"
ACTION_CLASSROOM_CREATED = "classroom_created"
ACTION_CLASSROOM_UPDATED = "classroom_updated"
ACTION_CLASSROOM_DELETED = "classroom_deleted"
ACTION_THRESHOLDS_UPDATED = "thresholds_updated"
ACTION_NOTIFICATIONS_READ = "notifications_read"

# Human-readable names, shared by the Audit Log viewer and case timelines.
ACTION_LABELS: dict[str, str] = {
    ACTION_SIGN_IN: "Signed in",
    ACTION_SECURITY_RELINK_REJECTED: "Security: account re-link rejected",
    ACTION_SIGN_OUT: "Signed out",
    ACTION_ADMIN_CREATE_USER: "Created user",
    ACTION_ADMIN_UPDATE_USER: "Updated user",
    ACTION_ADMIN_DELETE_USER: "Deleted user",
    ACTION_SEATMAP_UPLOAD: "Uploaded seat map",
    ACTION_DETECTION_RECORDED: "Detection recorded",
    ACTION_ALERT_CONFIRMED: "Confirmed alert as case",
    ACTION_CASE_TRANSITION: "Changed case status",
    ACTION_PENALTY_ISSUED: "Issued penalty",
    ACTION_NOTICE_GENERATED: "Generated notice",
    ACTION_APPEAL_SUBMITTED: "Submitted appeal",
    ACTION_APPEAL_RESOLVED: "Resolved appeal",
    ACTION_SNAPSHOTS_PURGED: "Purged dismissed evidence",
    ACTION_CLIP_STORED: "Stored evidence clip",
    ACTION_CLIPS_PURGED: "Purged reviewed clips",
    ACTION_MEDIA_VIEWED: "Viewed evidence",
    ACTION_SESSION_STARTED: "Started exam session",
    ACTION_SESSION_ENDED: "Ended exam session",
    ACTION_EXAM_SCHEDULED: "Scheduled exam",
    ACTION_EXAM_UPDATED: "Updated exam",
    ACTION_EXAM_CANCELLED: "Cancelled exam",
    ACTION_INVIGILATOR_ASSIGNED: "Assigned invigilator",
    ACTION_CLASSROOM_CREATED: "Created classroom",
    ACTION_CLASSROOM_UPDATED: "Updated classroom",
    ACTION_CLASSROOM_DELETED: "Deleted classroom",
    ACTION_THRESHOLDS_UPDATED: "Updated detection thresholds",
    ACTION_NOTIFICATIONS_READ: "Read notifications",
}
ACTION_CODES_BY_LABEL = {label: code for code, label in ACTION_LABELS.items()}


def action_label(code: str) -> str:
    return ACTION_LABELS.get(code, code.replace("_", " ").capitalize())


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
