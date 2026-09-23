"""Seat-map CSV parsing and resolution (seat_number,student_reg_no).

A row resolves only to an existing, activated (has signed in with Google)
student account. Unresolved rows are reported, never silently skipped and
never used to create accounts. An upload is the complete map for the
session: applying it replaces the previous one in a single transaction.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

import asyncpg

from app.models import SeatmapRowStatus
from app.schemas import SeatmapRowResult, SeatmapUploadResponse

MAX_SEATMAP_BYTES = 256 * 1024
MAX_SEATMAP_ROWS = 1000
MAX_SEAT_NUMBER = 1000
REQUIRED_COLUMNS = ("seat_number", "student_reg_no")
INVALID_SEAT = -1


class SeatmapError(ValueError):
    """The file itself is unusable (size, encoding, columns, duplicates)."""


@dataclass(frozen=True)
class ResolvedRow:
    seat_number: int
    student_reg_no: str
    status: SeatmapRowStatus
    student_id: str | None


def parse_seatmap(raw: bytes) -> list[tuple[int, str]]:
    if len(raw) > MAX_SEATMAP_BYTES:
        raise SeatmapError(f"Seat map must be at most {MAX_SEATMAP_BYTES // 1024} KB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SeatmapError("Seat map must be a UTF-8 CSV file.") from exc

    reader = csv.reader(io.StringIO(text))
    header = [cell.strip().lower() for cell in next(reader, [])]
    if not set(REQUIRED_COLUMNS).issubset(header):
        raise SeatmapError(f"CSV must have columns: {', '.join(REQUIRED_COLUMNS)}")
    seat_index, reg_index = header.index("seat_number"), header.index("student_reg_no")

    rows: list[tuple[int, str]] = []
    for cells in reader:
        if not any(cell.strip() for cell in cells):
            continue
        if len(rows) >= MAX_SEATMAP_ROWS:
            raise SeatmapError(f"Seat map may have at most {MAX_SEATMAP_ROWS} rows.")
        seat_text = cells[seat_index].strip() if seat_index < len(cells) else ""
        reg_no = cells[reg_index].strip() if reg_index < len(cells) else ""
        seat = int(seat_text) if seat_text.isdigit() and 1 <= int(seat_text) <= MAX_SEAT_NUMBER else INVALID_SEAT
        rows.append((seat, reg_no))

    if not rows:
        raise SeatmapError("CSV is empty or missing data rows.")
    seats = [seat for seat, _ in rows if seat != INVALID_SEAT]
    duplicate_seats = sorted({seat for seat in seats if seats.count(seat) > 1})
    if duplicate_seats:
        raise SeatmapError(f"Seat number(s) listed more than once: {', '.join(map(str, duplicate_seats))}.")
    regs = [reg for _, reg in rows if reg]
    duplicate_regs = sorted({reg for reg in regs if regs.count(reg) > 1})
    if duplicate_regs:
        raise SeatmapError(f"Registration number(s) seated more than once: {', '.join(duplicate_regs)}.")
    return rows


async def resolve_seatmap(conn: asyncpg.Connection, rows: list[tuple[int, str]]) -> list[ResolvedRow]:
    accounts = {
        row["registration_or_employee_no"]: row
        for row in await conn.fetch(
            """
            SELECT id, registration_or_employee_no, (supabase_user_id IS NOT NULL) AS activated
            FROM users
            WHERE role = 'student' AND deleted_at IS NULL AND status = 'active'
              AND registration_or_employee_no = ANY($1::text[])
            """,
            [reg for _, reg in rows],
        )
    }
    resolved: list[ResolvedRow] = []
    for seat, reg_no in rows:
        account = accounts.get(reg_no)
        if seat == INVALID_SEAT or account is None:
            resolved.append(ResolvedRow(seat, reg_no, SeatmapRowStatus.UNREGISTERED_ID, None))
        elif not account["activated"]:
            # The account exists but its owner has never signed in with Google.
            resolved.append(ResolvedRow(seat, reg_no, SeatmapRowStatus.UNVERIFIED, None))
        else:
            resolved.append(ResolvedRow(seat, reg_no, SeatmapRowStatus.RESOLVED, str(account["id"])))
    return resolved


async def replace_seat_assignments(conn: asyncpg.Connection, session_id: str, rows: list[ResolvedRow]) -> None:
    """Caller holds a transaction."""
    await conn.execute("DELETE FROM seat_assignments WHERE session_id = $1::uuid", session_id)
    await conn.executemany(
        """
        INSERT INTO seat_assignments (session_id, seat_number, student_reg_no, student_id)
        VALUES ($1::uuid, $2, $3, $4::uuid)
        """,
        [(session_id, r.seat_number, r.student_reg_no, r.student_id) for r in rows if r.status == SeatmapRowStatus.RESOLVED],
    )


def summarize(rows: list[ResolvedRow]) -> SeatmapUploadResponse:
    results = [SeatmapRowResult(seat_number=r.seat_number, student_reg_no=r.student_reg_no, status=r.status) for r in rows]
    resolved = sum(1 for r in rows if r.status == SeatmapRowStatus.RESOLVED)
    return SeatmapUploadResponse(rows=results, resolved_count=resolved, rejected_count=len(rows) - resolved)
