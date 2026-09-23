"""Institution-wide integrity statistics (aggregates only, no identities)."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import CurrentUser, get_db, require_role
from app.models import BehaviourType, CaseStatus, Role
from app.schemas import CountByLabel, StatisticsOut

router = APIRouter(prefix="/api/reports", tags=["reports"])

require_report_reader = require_role(Role.EXAM_CONTROLLER, Role.ADMIN, Role.HOD)
TREND_DAYS = 30


@router.get("/statistics", response_model=StatisticsOut)
async def statistics(
    current_user: CurrentUser = Depends(require_report_reader),
    conn: asyncpg.Connection = Depends(get_db),
) -> StatisticsOut:
    by_department = await conn.fetch(
        """
        SELECT COALESCE(NULLIF(s.department, ''), 'Unassigned') AS label, count(*) AS count
        FROM cases c JOIN exam_sessions s ON s.id = c.session_id
        GROUP BY 1 ORDER BY count DESC, label
        """
    )
    over_time = await conn.fetch(
        """
        SELECT to_char((c.created_at AT TIME ZONE $1)::date, 'YYYY-MM-DD') AS label, count(*) AS count
        FROM cases c
        WHERE c.created_at >= now() - make_interval(days => $2)
        GROUP BY 1 ORDER BY 1
        """,
        settings.institution_timezone,
        TREND_DAYS,
    )
    behaviours = {
        r["label"]: r["count"]
        for r in await conn.fetch(
            """
            SELECT b AS label, count(*) AS count
            FROM cases c JOIN detection_events de ON de.id = c.detection_event_id, unnest(de.behaviour_types) AS b
            GROUP BY b
            """
        )
    }
    statuses = {r["status"]: r["count"] for r in await conn.fetch("SELECT status, count(*) AS count FROM cases GROUP BY status")}
    appeals = await conn.fetchrow(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE status = 'accepted') AS accepted,
               count(*) FILTER (WHERE status <> 'open') AS resolved
        FROM appeals
        """
    )
    # A case is resolved when dismissed, or when its penalty was issued.
    avg_days = await conn.fetchval(
        """
        SELECT avg(EXTRACT(EPOCH FROM (COALESCE(p.created_at, c.updated_at) - c.created_at)) / 86400)
        FROM cases c LEFT JOIN penalties p ON p.case_id = c.id
        WHERE c.status = 'dismissed' OR p.id IS NOT NULL
        """
    )
    return StatisticsOut(
        incidents_by_department=[CountByLabel(label=r["label"], count=r["count"]) for r in by_department],
        incidents_over_time=[CountByLabel(label=r["label"], count=r["count"]) for r in over_time],
        behavior_distribution=[CountByLabel(label=b.value, count=behaviours.get(b.value, 0)) for b in BehaviourType],
        case_status_distribution=[CountByLabel(label=s.value, count=statuses.get(s.value, 0)) for s in CaseStatus],
        total_cases=sum(statuses.values()),
        total_appeals=appeals["total"],
        appeal_success_rate=round(appeals["accepted"] / appeals["resolved"], 3) if appeals["resolved"] else 0.0,
        average_resolution_days=round(float(avg_days), 1) if avg_days is not None else 0.0,
    )
