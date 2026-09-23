"""Classrooms and their seat polygon maps (Admin manages; staff read)."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.audit import ACTION_CLASSROOM_CREATED, ACTION_CLASSROOM_DELETED, ACTION_CLASSROOM_UPDATED, record_audit
from app.deps import CurrentUser, get_client_ip, get_db, require_admin, require_role
from app.models import CameraStatus, Role
from app.schemas import ClassroomCreate, ClassroomOut, ClassroomUpdate, SeatPolygon

router = APIRouter(tags=["classrooms"])

require_staff = require_role(Role.ADMIN, Role.HOD, Role.TEACHER, Role.EXAM_CONTROLLER)
CLASSROOM_COLUMNS = "id, name, building, capacity, camera_id, camera_status, seat_map, created_at"
ERR_NOT_FOUND = "Classroom not found."
ERR_NAME_TAKEN = "A classroom with this name already exists."


def _row_to_classroom(row: asyncpg.Record) -> ClassroomOut:
    raw = row["seat_map"]
    seats = json.loads(raw) if isinstance(raw, str) else raw
    return ClassroomOut(
        id=str(row["id"]),
        name=row["name"],
        building=row["building"],
        capacity=row["capacity"],
        camera_id=row["camera_id"],
        camera_status=CameraStatus(row["camera_status"]),
        seat_map=[SeatPolygon.model_validate(seat) for seat in seats] if seats else None,
        created_at=row["created_at"],
    )


def _seat_map_json(seat_map: list[SeatPolygon] | None) -> str | None:
    # An empty map is stored as "not configured".
    return json.dumps([seat.model_dump() for seat in seat_map]) if seat_map else None


def _audit_value(changes: dict[str, Any]) -> dict[str, Any]:
    value = {key: (v.value if hasattr(v, "value") else v) for key, v in changes.items() if key != "seat_map"}
    if "seat_map" in changes:
        value["seats_mapped"] = len(changes["seat_map"] or [])
    return value


@router.get("/api/classrooms", response_model=list[ClassroomOut])
async def list_classrooms(
    current_user: CurrentUser = Depends(require_staff),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[ClassroomOut]:
    rows = await conn.fetch(f"SELECT {CLASSROOM_COLUMNS} FROM classrooms ORDER BY building, name")
    return [_row_to_classroom(row) for row in rows]


@router.get("/api/classrooms/{classroom_id}", response_model=ClassroomOut)
async def get_classroom(
    classroom_id: UUID,
    current_user: CurrentUser = Depends(require_staff),
    conn: asyncpg.Connection = Depends(get_db),
) -> ClassroomOut:
    row = await conn.fetchrow(f"SELECT {CLASSROOM_COLUMNS} FROM classrooms WHERE id = $1", classroom_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
    return _row_to_classroom(row)


@router.post("/api/admin/classrooms", response_model=ClassroomOut, status_code=status.HTTP_201_CREATED)
async def create_classroom(
    body: ClassroomCreate,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_db),
) -> ClassroomOut:
    async with conn.transaction():
        try:
            row = await conn.fetchrow(
                f"""
                INSERT INTO classrooms (name, building, capacity, camera_id, camera_status, seat_map)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                RETURNING {CLASSROOM_COLUMNS}
                """,
                body.name.strip(),
                body.building.strip(),
                body.capacity,
                (body.camera_id or "").strip() or None,
                body.camera_status.value,
                _seat_map_json(body.seat_map),
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERR_NAME_TAKEN) from exc
        await record_audit(
            conn, actor_id=current_user.user_id, action=ACTION_CLASSROOM_CREATED, target=str(row["id"]),
            new_value=_audit_value(body.model_dump()), ip_address=get_client_ip(request),
        )
    return _row_to_classroom(row)


@router.patch("/api/admin/classrooms/{classroom_id}", response_model=ClassroomOut)
async def update_classroom(
    classroom_id: UUID,
    body: ClassroomUpdate,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_db),
) -> ClassroomOut:
    changes = body.model_dump(exclude_unset=True)
    for required in ("name", "building", "capacity", "camera_status"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{required} cannot be empty.")
    async with conn.transaction():
        existing = await conn.fetchrow(f"SELECT {CLASSROOM_COLUMNS} FROM classrooms WHERE id = $1 FOR UPDATE", classroom_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
        seat_map = body.seat_map if "seat_map" in changes else None
        try:
            row = await conn.fetchrow(
                f"""
                UPDATE classrooms SET name = $2, building = $3, capacity = $4, camera_id = $5, camera_status = $6,
                                      seat_map = CASE WHEN $8 THEN $7::jsonb ELSE seat_map END
                WHERE id = $1
                RETURNING {CLASSROOM_COLUMNS}
                """,
                classroom_id,
                (changes.get("name") or existing["name"]).strip(),
                (changes.get("building") or existing["building"]).strip(),
                changes.get("capacity") or existing["capacity"],
                ((changes["camera_id"] or "").strip() or None) if "camera_id" in changes else existing["camera_id"],
                (changes.get("camera_status") or CameraStatus(existing["camera_status"])).value,
                _seat_map_json(seat_map),
                "seat_map" in changes,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERR_NAME_TAKEN) from exc
        await record_audit(
            conn, actor_id=current_user.user_id, action=ACTION_CLASSROOM_UPDATED, target=str(classroom_id),
            new_value=_audit_value(changes), ip_address=get_client_ip(request),
        )
    return _row_to_classroom(row)


@router.delete("/api/admin/classrooms/{classroom_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_classroom(
    classroom_id: UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    conn: asyncpg.Connection = Depends(get_db),
) -> Response:
    async with conn.transaction():
        if await conn.fetchval("SELECT 1 FROM exam_sessions WHERE classroom_id = $1 LIMIT 1", classroom_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This classroom has exam sessions on record and cannot be deleted.")
        name = await conn.fetchval("DELETE FROM classrooms WHERE id = $1 RETURNING name", classroom_id)
        if name is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERR_NOT_FOUND)
        await record_audit(
            conn, actor_id=current_user.user_id, action=ACTION_CLASSROOM_DELETED, target=str(classroom_id),
            new_value={"name": name}, ip_address=get_client_ip(request),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
