"""Evidence retention, run hourly inside the always-on API process.

1. Clips: deleted from Storage once the review is final (REVIEW_FINAL_SQL);
   the contact-sheet record image made from the clip stays.
2. Dismissed cases: after `snapshot_retention_days` the snapshot and record
   image are deleted too; a cleared student's images serve no record purpose.
Evidence behind pending, escalated, or confirmed-without-penalty cases is
never touched.

A Redis lock keeps two instances from running this at once during a rolling
deploy's overlap window.
"""
from __future__ import annotations

import asyncio
import logging

import asyncpg
import httpx
from redis.exceptions import RedisError

from app.audit import ACTION_CLIPS_PURGED, ACTION_SNAPSHOTS_PURGED, record_audit
from app.config import settings
from app.db import acquire_connection
from app.redis_client import get_redis
from app.services.storage import SupabaseStorage

logger = logging.getLogger("proctorai.retention")

PURGE_BATCH_SIZE = 500
RETENTION_LOCK_KEY = "lock:evidence-retention"

# Review is final when the case was dismissed (plus a grace period), or a
# penalty was issued and the appeal window has closed. When appeals are
# stored server-side, add "and no appeal is open" here; this is the only
# place the rule lives.
REVIEW_FINAL_SQL = """
    (c.status = 'dismissed' AND c.updated_at < now() - make_interval(hours => $1))
    OR (c.status = 'confirmed' AND p.created_at < now() - make_interval(days => $2))
"""


async def purge_finalized_clips(conn: asyncpg.Connection, storage: SupabaseStorage) -> int:
    rows = await conn.fetch(
        f"""
        SELECT de.id, de.clip_path
        FROM detection_events de
        JOIN cases c ON c.detection_event_id = de.id
        LEFT JOIN penalties p ON p.case_id = c.id
        WHERE de.clip_path IS NOT NULL AND de.clip_purged_at IS NULL
          AND ({REVIEW_FINAL_SQL})
        LIMIT $3
        """,
        settings.clip_grace_hours_after_dismissal,
        settings.appeal_window_days,
        PURGE_BATCH_SIZE,
    )
    if not rows:
        return 0

    await storage.delete([row["clip_path"] for row in rows])
    ids = [row["id"] for row in rows]
    await conn.execute("UPDATE detection_events SET clip_purged_at = now() WHERE id = ANY($1::uuid[])", ids)
    await record_audit(
        conn,
        actor_id=None,
        action=ACTION_CLIPS_PURGED,
        target="detection_events",
        new_value={"count": len(rows), "detection_ids": [str(i) for i in ids]},
        ip_address=None,
    )
    return len(rows)


async def purge_dismissed_evidence(conn: asyncpg.Connection, storage: SupabaseStorage) -> int:
    rows = await conn.fetch(
        """
        SELECT de.id, de.snapshot_path, de.record_image_path
        FROM detection_events de
        JOIN cases c ON c.detection_event_id = de.id
        WHERE de.snapshot_purged_at IS NULL
          AND c.status = 'dismissed'
          AND c.updated_at < now() - make_interval(days => $1)
        ORDER BY c.updated_at
        LIMIT $2
        """,
        settings.snapshot_retention_days,
        PURGE_BATCH_SIZE,
    )
    if not rows:
        return 0

    paths = [row["snapshot_path"] for row in rows] + [row["record_image_path"] for row in rows if row["record_image_path"]]
    await storage.delete(paths)
    ids = [row["id"] for row in rows]
    await conn.execute("UPDATE detection_events SET snapshot_purged_at = now() WHERE id = ANY($1::uuid[])", ids)
    await record_audit(
        conn,
        actor_id=None,
        action=ACTION_SNAPSHOTS_PURGED,
        target="detection_events",
        new_value={"count": len(rows), "detection_ids": [str(i) for i in ids]},
        ip_address=None,
    )
    return len(rows)


async def run_retention_loop(storage: SupabaseStorage) -> None:
    lock_ttl = max(settings.snapshot_purge_interval_seconds - 60, 60)
    while True:
        try:
            if await get_redis().set(RETENTION_LOCK_KEY, "1", nx=True, ex=lock_ttl):
                async with acquire_connection() as conn:
                    clips = await purge_finalized_clips(conn, storage)
                    evidence = await purge_dismissed_evidence(conn, storage)
                logger.info("evidence retention complete clips=%d dismissed_evidence=%d", clips, evidence)
        except (asyncpg.PostgresError, httpx.HTTPError, RedisError, OSError):
            logger.exception("evidence retention failed; will retry next interval")
        await asyncio.sleep(settings.snapshot_purge_interval_seconds)
