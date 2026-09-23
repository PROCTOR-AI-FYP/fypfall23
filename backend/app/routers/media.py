"""Evidence clips: upload from the detection worker, review access for staff.

POST /internal/cases/{case_id}/clip        raw video body -> compressed MP4 +
                                           record JPEG in Supabase Storage
GET  /api/cases/{case_id}/media            signed URLs for review
GET  /api/detections/{detection_id}/media  same, keyed by detection

The upload is a raw request body (Content-Type: video/*), not multipart, so
the size cap is enforced while streaming instead of after the whole file has
been buffered.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import ACTION_CLIP_STORED, ACTION_MEDIA_VIEWED, record_audit
from app.config import settings
from app.deps import CurrentUser, get_client_ip, get_db, require_internal_api_key, require_role
from app.models import ClipStatus, Role
from app.schemas import CaseMediaOut, ClipStoredOut, MediaClipOut
from app.services.authorization import can_review_evidence
from app.services.media import MediaProcessingError, MediaToolMissingError, compress_clip
from app.services.storage import StorageNotConfiguredError, SupabaseStorage, get_storage

logger = logging.getLogger("proctorai.media")

internal_router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_api_key)])
router = APIRouter(prefix="/api", tags=["media"])

require_evidence_reviewer = require_role(Role.TEACHER, Role.HOD)

MEDIA_SELECT = """
    SELECT de.id AS detection_id, de.session_id, de.snapshot_path, de.snapshot_purged_at,
           de.clip_path, de.clip_bytes, de.clip_duration_seconds, de.clip_purged_at, de.record_image_path,
           c.id AS case_id, s.invigilator_id
    FROM detection_events de
    JOIN exam_sessions s ON s.id = de.session_id
    LEFT JOIN cases c ON c.detection_event_id = de.id
"""


def _storage_or_503() -> SupabaseStorage:
    try:
        return get_storage()
    except StorageNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Evidence storage is not configured.") from exc


async def _save_body(request: Request, destination: Path) -> None:
    written = 0
    with destination.open("wb") as out:
        async for chunk in request.stream():
            written += len(chunk)
            if written > settings.clip_max_upload_bytes:
                raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Clip exceeds the upload limit.")
            out.write(chunk)
    if written == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Request body is empty.")


@internal_router.post("/cases/{case_id}/clip", response_model=ClipStoredOut, status_code=status.HTTP_201_CREATED)
async def upload_clip(case_id: UUID, request: Request, conn: asyncpg.Connection = Depends(get_db)) -> ClipStoredOut:
    storage = _storage_or_503()
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > settings.clip_max_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Clip exceeds the upload limit.")

    detection = await conn.fetchrow(
        """
        SELECT de.id, de.session_id, de.clip_path, de.clip_purged_at
        FROM cases c JOIN detection_events de ON de.id = c.detection_event_id
        WHERE c.id = $1
        """,
        case_id,
    )
    if detection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found or has no detection event.")
    if detection["clip_path"] is not None or detection["clip_purged_at"] is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A clip has already been stored for this case.")

    with tempfile.TemporaryDirectory(prefix="proctorai-clip-") as workdir:
        source = Path(workdir) / "upload"
        await _save_body(request, source)
        try:
            clip = await compress_clip(source, Path(workdir))
        except MediaProcessingError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        except MediaToolMissingError as exc:
            logger.error("%s", exc)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Clip processing is unavailable.") from exc

    session_id, detection_id = str(detection["session_id"]), str(detection["id"])
    clip_path = f"{settings.supabase_clip_bucket}/{session_id}/{detection_id}.mp4"
    record_path = f"{settings.supabase_snapshot_bucket}/{session_id}/{detection_id}-record.jpg"
    try:
        await storage.upload(clip_path, clip.video, "video/mp4")
        try:
            await storage.upload(record_path, clip.record_image, "image/jpeg")
        except httpx.HTTPError:
            await storage.delete([clip_path])
            raise
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == status.HTTP_409_CONFLICT:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A clip has already been stored for this case.") from exc
        logger.error("evidence upload failed status=%s", exc.response.status_code)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Evidence storage is unavailable.") from exc
    except httpx.HTTPError as exc:
        logger.error("evidence upload failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Evidence storage is unavailable.") from exc

    async with conn.transaction():
        updated = await conn.fetchval(
            """
            UPDATE detection_events
            SET clip_path = $1, clip_bytes = $2, clip_duration_seconds = $3, clip_uploaded_at = now(),
                record_image_path = $4
            WHERE id = $5 AND clip_path IS NULL AND clip_purged_at IS NULL
            RETURNING id
            """,
            clip_path,
            len(clip.video),
            clip.duration_seconds,
            record_path,
            detection["id"],
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A clip has already been stored for this case.")
        await record_audit(
            conn,
            actor_id=None,
            action=ACTION_CLIP_STORED,
            target=str(case_id),
            new_value={"original_bytes": clip.original_bytes, "stored_bytes": len(clip.video),
                       "duration_seconds": clip.duration_seconds},
            ip_address=None,
        )

    return ClipStoredOut(
        detection_id=detection_id,
        duration_seconds=clip.duration_seconds,
        original_bytes=clip.original_bytes,
        stored_bytes=len(clip.video),
    )


async def _media_response(
    row: asyncpg.Record | None, current_user: CurrentUser, request: Request, conn: asyncpg.Connection
) -> CaseMediaOut:
    invigilator_id = str(row["invigilator_id"]) if row is not None and row["invigilator_id"] is not None else None
    if row is None or not can_review_evidence(
        role=current_user.role, user_id=current_user.user_id, invigilator_id=invigilator_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found.")

    storage = _storage_or_503()
    if row["clip_purged_at"] is not None:
        clip_status = ClipStatus.DELETED_AFTER_REVIEW
    elif row["clip_path"] is not None:
        clip_status = ClipStatus.AVAILABLE
    else:
        clip_status = ClipStatus.PENDING_UPLOAD

    images_kept = row["snapshot_purged_at"] is None
    wanted = {
        "clip": row["clip_path"] if clip_status == ClipStatus.AVAILABLE else None,
        "record": row["record_image_path"] if images_kept else None,
        "snapshot": row["snapshot_path"] if images_kept else None,
    }
    ttl = settings.media_url_ttl_seconds
    try:
        signed = await asyncio.gather(*(storage.signed_url(path, ttl) if path else _none() for path in wanted.values()))
    except httpx.HTTPError as exc:
        logger.error("signing evidence URLs failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Evidence storage is unavailable.") from exc
    urls = dict(zip(wanted, signed, strict=True))

    await record_audit(
        conn,
        actor_id=current_user.user_id,
        action=ACTION_MEDIA_VIEWED,
        target=str(row["detection_id"]),
        new_value={"clip_status": clip_status.value},
        ip_address=get_client_ip(request),
    )
    if current_user.role == Role.TEACHER:
        # The invigilator has looked at the evidence: the alert is now "reviewed".
        await conn.execute(
            "UPDATE detection_events SET reviewed_at = now() WHERE id = $1 AND reviewed_at IS NULL", row["detection_id"]
        )
    return CaseMediaOut(
        case_id=str(row["case_id"]) if row["case_id"] is not None else None,
        detection_id=str(row["detection_id"]),
        clip_status=clip_status,
        clip=MediaClipOut(
            url=urls["clip"],
            expires_in_seconds=ttl,
            duration_seconds=float(row["clip_duration_seconds"]),
            size_bytes=row["clip_bytes"],
        ) if urls["clip"] else None,
        record_image_url=urls["record"],
        snapshot_url=urls["snapshot"],
        clip_deleted_at=row["clip_purged_at"],
    )


async def _none() -> None:
    return None


@router.get("/cases/{case_id}/media", response_model=CaseMediaOut)
async def get_case_media(
    case_id: UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_evidence_reviewer),
    conn: asyncpg.Connection = Depends(get_db),
) -> CaseMediaOut:
    row = await conn.fetchrow(f"{MEDIA_SELECT} WHERE c.id = $1", case_id)
    return await _media_response(row, current_user, request, conn)


@router.get("/detections/{detection_id}/media", response_model=CaseMediaOut)
async def get_detection_media(
    detection_id: UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_evidence_reviewer),
    conn: asyncpg.Connection = Depends(get_db),
) -> CaseMediaOut:
    row = await conn.fetchrow(f"{MEDIA_SELECT} WHERE de.id = $1", detection_id)
    return await _media_response(row, current_user, request, conn)
