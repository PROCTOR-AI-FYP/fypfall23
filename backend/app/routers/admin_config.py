"""Admin configuration: detection thresholds, and the audit log (read-only)."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, Request

from app.audit import ACTION_CODES_BY_LABEL, ACTION_THRESHOLDS_UPDATED, action_label, record_audit
from app.deps import CurrentUser, get_client_ip, get_db, require_admin
from app.models import BehaviourType, Role
from app.schemas import AuditLogEntryOut, ThresholdOut, ThresholdSet
from app.services.clock import institution_zone
from app.services.detection import forget_detection_config

router = APIRouter(prefix="/api/admin", tags=["admin"])

AUDIT_PAGE_LIMIT = 500
# Keys whose values are identifiers or free text better left to the row detail.
_DETAIL_SKIP = {"detection_ids"}


def _details(new_value: Any) -> str:
    value = json.loads(new_value) if isinstance(new_value, str) else dict(new_value or {})
    parts = []
    for key, item in value.items():
        if key in _DETAIL_SKIP or item in (None, "", [], {}):
            continue
        parts.append(f"{key.replace('_', ' ')}: {item if not isinstance(item, (list, dict)) else json.dumps(item)}")
    return "; ".join(parts)


async def _thresholds(conn: asyncpg.Connection) -> list[ThresholdOut]:
    rows = await conn.fetch(
        """
        SELECT t.behaviour_type, t.sensitivity, t.weight, t.updated_at, u.full_name AS updated_by_name
        FROM detection_thresholds t LEFT JOIN users u ON u.id = t.updated_by
        """
    )
    order = [b.value for b in BehaviourType]
    return sorted(
        (
            ThresholdOut(
                behaviour_type=BehaviourType(r["behaviour_type"]),
                sensitivity=r["sensitivity"],
                weight=float(r["weight"]),
                updated_at=r["updated_at"],
                updated_by_name=r["updated_by_name"],
            )
            for r in rows
        ),
        key=lambda t: order.index(t.behaviour_type.value),
    )


@router.get("/thresholds", response_model=list[ThresholdOut])
async def get_thresholds(
    current_user: CurrentUser = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[ThresholdOut]:
    return await _thresholds(conn)


@router.put("/thresholds", response_model=list[ThresholdOut])
async def update_thresholds(
    body: ThresholdSet,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[ThresholdOut]:
    async with conn.transaction():
        before = {r["behaviour_type"]: (r["sensitivity"], float(r["weight"]))
                  for r in await conn.fetch("SELECT behaviour_type, sensitivity, weight FROM detection_thresholds")}
        await conn.executemany(
            """
            INSERT INTO detection_thresholds (behaviour_type, sensitivity, weight, updated_by, updated_at)
            VALUES ($1, $2, $3, $4::uuid, now())
            ON CONFLICT (behaviour_type) DO UPDATE
                SET sensitivity = EXCLUDED.sensitivity, weight = EXCLUDED.weight,
                    updated_by = EXCLUDED.updated_by, updated_at = now()
            """,
            [(t.behaviour_type.value, t.sensitivity, round(t.weight, 3), current_user.user_id) for t in body],
        )
        await record_audit(
            conn,
            actor_id=current_user.user_id,
            action=ACTION_THRESHOLDS_UPDATED,
            target="detection_thresholds",
            new_value={
                t.behaviour_type.value: {"sensitivity": t.sensitivity, "weight": round(t.weight, 3),
                                         "previous": list(before.get(t.behaviour_type.value, ()))}
                for t in body
            },
            ip_address=get_client_ip(request),
        )
    forget_detection_config()
    return await _thresholds(conn)


@router.get("/audit-log", response_model=list[AuditLogEntryOut])
async def get_audit_log(
    action: str | None = Query(default=None, max_length=80),
    user_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=AUDIT_PAGE_LIMIT, ge=1, le=AUDIT_PAGE_LIMIT),
    current_user: CurrentUser = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[AuditLogEntryOut]:
    # The viewer filters by the label it displays; accept either form.
    action_code = ACTION_CODES_BY_LABEL.get(action, action) if action else None
    zone = institution_zone()
    start = datetime.combine(date_from, time.min, zone) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min, zone) if date_to else None
    rows = await conn.fetch(
        """
        SELECT al.id, al.actor_id, al.action, al.target, al.new_value, al.ip_address, al.created_at,
               u.full_name, u.role
        FROM audit_log al LEFT JOIN users u ON u.id = al.actor_id
        WHERE ($1::text IS NULL OR al.action = $1)
          AND ($2::uuid IS NULL OR al.actor_id = $2::uuid)
          AND ($3::timestamptz IS NULL OR al.created_at >= $3)
          AND ($4::timestamptz IS NULL OR al.created_at < $4)
        ORDER BY al.created_at DESC, al.id DESC
        LIMIT $5
        """,
        action_code,
        str(user_id) if user_id else None,
        start,
        end,
        limit,
    )
    return [
        AuditLogEntryOut(
            id=str(r["id"]),
            timestamp=r["created_at"],
            user_id=str(r["actor_id"]) if r["actor_id"] else None,
            user_name=r["full_name"] or "System",
            user_role=Role(r["role"]) if r["role"] else None,
            action=action_label(r["action"]),
            action_code=r["action"],
            target=r["target"],
            details=_details(r["new_value"]),
            ip_address=r["ip_address"],
        )
        for r in rows
    ]
