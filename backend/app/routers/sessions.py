"""Seat-map upload — the join between a signed-up, verified student and a
seat. A row that doesn't resolve is reported back, never silently skipped
and never used to auto-create an account.
"""
from __future__ import annotations

import csv
import io

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status

from app.audit import ACTION_SEATMAP_UPLOAD, record_audit
from app.deps import CurrentUser, get_client_ip, get_db, require_role
from app.models import Role, SeatmapRowStatus
from app.schemas import SeatmapRowResult, SeatmapUploadResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

require_seatmap_uploader = require_role(Role.ADMIN, Role.EXAM_CONTROLLER)

CSV_REQUIRED_COLUMNS = {"seat_number", "student_reg_no"}


@router.post("/{session_id}/seatmap", response_model=SeatmapUploadResponse)
async def upload_seatmap(
    session_id: str,
    file: UploadFile,
    request: Request,
    current_user: CurrentUser = Depends(require_seatmap_uploader),
    conn: asyncpg.Connection = Depends(get_db),
) -> SeatmapUploadResponse:
    session_exists = await conn.fetchval("SELECT 1 FROM exam_sessions WHERE id = $1", session_id)
    if not session_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam session not found.")

    raw_bytes = await file.read()
    text = raw_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None or not CSV_REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"CSV must have columns: {', '.join(sorted(CSV_REQUIRED_COLUMNS))}",
        )

    results: list[SeatmapRowResult] = []
    for raw_row in reader:
        seat_number_str = raw_row["seat_number"].strip()
        student_reg_no = raw_row["student_reg_no"].strip()
        try:
            seat_number = int(seat_number_str)
        except ValueError:
            results.append(
                SeatmapRowResult(
                    seat_number=-1, student_reg_no=student_reg_no, status=SeatmapRowStatus.UNREGISTERED_ID
                )
            )
            continue

        student = await conn.fetchrow(
            """
            SELECT id, (supabase_user_id IS NOT NULL) AS activated FROM users
            WHERE registration_or_employee_no = $1 AND role = 'student' AND deleted_at IS NULL
            """,
            student_reg_no,
        )

        if student is None:
            row_status = SeatmapRowStatus.UNREGISTERED_ID
        elif not student["activated"]:
            # The account exists but its owner has never signed in with Google.
            row_status = SeatmapRowStatus.UNVERIFIED
        else:
            row_status = SeatmapRowStatus.RESOLVED
            await conn.execute(
                """
                INSERT INTO seat_assignments (session_id, seat_number, student_reg_no, student_id)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (session_id, seat_number)
                DO UPDATE SET student_reg_no = EXCLUDED.student_reg_no, student_id = EXCLUDED.student_id
                """,
                session_id,
                seat_number,
                student_reg_no,
                student["id"],
            )

        results.append(SeatmapRowResult(seat_number=seat_number, student_reg_no=student_reg_no, status=row_status))

    resolved_count = sum(1 for r in results if r.status == SeatmapRowStatus.RESOLVED)
    rejected_count = len(results) - resolved_count

    await record_audit(
        conn,
        actor_id=current_user.user_id,
        action=ACTION_SEATMAP_UPLOAD,
        target=session_id,
        new_value={"resolved_count": resolved_count, "rejected_count": rejected_count},
        ip_address=get_client_ip(request),
    )

    return SeatmapUploadResponse(rows=results, resolved_count=resolved_count, rejected_count=rejected_count)
