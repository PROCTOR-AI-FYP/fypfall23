"""Writing notifications (the header bell's inbox).

Always called inside the transaction of the event it reports, so a
notification never outlives a rolled-back change. Only titles and short
factual messages are stored; nothing here is evidence.
"""
from __future__ import annotations

import asyncpg

from app.models import NotificationType, Role


async def notify_users(
    conn: asyncpg.Connection,
    user_ids: list[str],
    *,
    type_: NotificationType,
    title: str,
    message: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> None:
    if not user_ids:
        return
    await conn.executemany(
        """
        INSERT INTO notifications (user_id, type, title, message, reference_type, reference_id)
        VALUES ($1::uuid, $2, $3, $4, $5, $6::uuid)
        """,
        [(user_id, type_.value, title, message, reference_type, reference_id) for user_id in user_ids],
    )


async def notify_role(
    conn: asyncpg.Connection,
    role: Role,
    *,
    type_: NotificationType,
    title: str,
    message: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> None:
    rows = await conn.fetch(
        "SELECT id FROM users WHERE role = $1 AND status = 'active' AND deleted_at IS NULL", role.value
    )
    await notify_users(
        conn,
        [str(row["id"]) for row in rows],
        type_=type_,
        title=title,
        message=message,
        reference_type=reference_type,
        reference_id=reference_id,
    )
