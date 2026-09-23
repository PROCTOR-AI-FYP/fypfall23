"""The signed-in user's notifications. Scoped by RLS as well as by the query:
through get_rls_db, a user can neither read nor mark anyone else's rows."""
from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.audit import ACTION_NOTIFICATIONS_READ, record_audit
from app.deps import CurrentUser, get_client_ip, get_rls_db, require_any_role
from app.models import NotificationType
from app.schemas import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

NOTIFICATION_LIMIT = 100


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    current_user: CurrentUser = Depends(require_any_role),
    conn: asyncpg.Connection = Depends(get_rls_db),
) -> list[NotificationOut]:
    rows = await conn.fetch(
        """
        SELECT id, type, title, message, reference_type, reference_id, read_at, created_at
        FROM notifications WHERE user_id = $1::uuid
        ORDER BY created_at DESC LIMIT $2
        """,
        current_user.user_id,
        NOTIFICATION_LIMIT,
    )
    return [
        NotificationOut(
            id=str(row["id"]),
            type=NotificationType(row["type"]),
            title=row["title"],
            message=row["message"],
            reference_type=row["reference_type"],
            reference_id=str(row["reference_id"]) if row["reference_id"] else None,
            read=row["read_at"] is not None,
            created_at=row["created_at"],
        )
        for row in rows
    ]


async def _mark_read(conn: asyncpg.Connection, request: Request, current_user: CurrentUser, notification_id: UUID | None) -> int:
    marked = await conn.fetch(
        """
        UPDATE notifications SET read_at = now()
        WHERE user_id = $1::uuid AND read_at IS NULL AND ($2::uuid IS NULL OR id = $2::uuid)
        RETURNING id
        """,
        current_user.user_id,
        str(notification_id) if notification_id else None,
    )
    if marked:
        await record_audit(
            conn, actor_id=current_user.user_id, action=ACTION_NOTIFICATIONS_READ, target=current_user.user_id,
            new_value={"count": len(marked)}, ip_address=get_client_ip(request),
        )
    return len(marked)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notification_id: UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_any_role),
    conn: asyncpg.Connection = Depends(get_rls_db),
) -> Response:
    if not await conn.fetchval("SELECT 1 FROM notifications WHERE id = $1 AND user_id = $2::uuid", notification_id, current_user.user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")
    await _mark_read(conn, request, current_user, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    request: Request,
    current_user: CurrentUser = Depends(require_any_role),
    conn: asyncpg.Connection = Depends(get_rls_db),
) -> Response:
    await _mark_read(conn, request, current_user, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
