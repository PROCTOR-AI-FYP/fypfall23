"""Validate and atomically apply the four exam-setup CSV templates.

Imports create records or skip exact matches. They never re-role, activate,
re-link or silently overwrite accounts, rooms or exams. Planning includes new
rooms/exams in the same batch, so files can be submitted together.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, time
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException, Request
from pydantic import ValidationError

from app.deps import CurrentUser
from app.models import CameraStatus, Role
from app.routers.admin_users import _validate_email_role_pairing, admin_create_user
from app.routers.classrooms import create_classroom
from app.routers.schedule import assign_invigilator, schedule_exam, _validate_slot
from app.schemas import AdminCreateUserRequest, AssignInvigilatorRequest, ClassroomCreate, ExamScheduleCreate
from app.security import local_part_of, normalize_email

MAX_BYTES = 256 * 1024
MAX_ROWS = 1000
HEADERS = {
    "student_roster": ("student_reg_no", "full_name", "university_email", "department"),
    "classroom_inventory": ("room_name", "building", "capacity", "camera_id", "camera_status"),
    "exam_schedule": ("course_code", "course_name", "department", "date", "start_time", "end_time", "room_name"),
    "invigilator_assignments": ("teacher_email", "course_code", "date", "start_time", "end_time", "room_name"),
}


@dataclass
class ImportRow:
    kind: str
    line: int
    label: str
    action: str = "create"
    note: str = "Ready to import."
    values: dict[str, Any] = field(default_factory=dict)
    existing_id: str | None = None

    def public(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in ("kind", "line", "label", "action", "note")}


@dataclass
class ImportPlan:
    rows: list[ImportRow]
    fingerprint: str

    def public(self) -> dict[str, Any]:
        counts = {action: sum(row.action == action for row in self.rows) for action in ("create", "skip", "error")}
        return {"rows": [row.public() for row in self.rows], "counts": counts,
                "can_import": counts["error"] == 0 and counts["create"] > 0,
                "preview_hash": self.fingerprint}


def parse_csv(kind: str, raw: bytes) -> list[tuple[int, dict[str, str]]]:
    if len(raw) > MAX_BYTES:
        raise ValueError("Each CSV must be at most 256 KB.")
    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        header = [c.strip().lower() for c in next(reader, [])]
        if len(header) != len(set(header)):
            raise ValueError("CSV contains duplicate column names.")
        missing = set(HEADERS[kind]) - set(header)
        extra = set(header) - set(HEADERS[kind])
        if missing or extra:
            raise ValueError("Expected columns: " + ", ".join(HEADERS[kind]) + ".")
        rows = []
        for cells in reader:
            if not any(c.strip() for c in cells):
                continue
            if len(cells) != len(header):
                raise ValueError(f"CSV line {reader.line_num} has the wrong number of fields.")
            if len(rows) >= MAX_ROWS:
                raise ValueError("Each CSV may contain at most 1000 data rows.")
            rows.append((reader.line_num, dict(zip(header, (c.strip() for c in cells)))))
        if not rows:
            raise ValueError("Fill in the template first; the CSV has no data rows.")
        return rows
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("Upload a valid UTF-8 CSV file.") from exc


def _slot(values: dict[str, str]) -> tuple[date, time, time]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values["date"]):
        raise ValueError("Use YYYY-MM-DD for the date.")
    if not all(re.fullmatch(r"\d{2}:\d{2}", values[k]) for k in ("start_time", "end_time")):
        raise ValueError("Use 24-hour HH:MM for start and end times.")
    day, start, end = date.fromisoformat(values["date"]), time.fromisoformat(values["start_time"]), time.fromisoformat(values["end_time"])
    _validate_slot(day, start, end)
    return day, start, end


def _exam_key(code: str, day: date, start: time, end: time, room: str) -> tuple:
    return (code.strip().upper(), day, start, end, room.casefold())


def _error(row: ImportRow, note: str) -> None:
    row.action, row.note = "error", note


async def build_plan(conn: asyncpg.Connection, files: dict[str, bytes]) -> ImportPlan:
    users = await conn.fetch("SELECT id,full_name,email,role,department,registration_or_employee_no,status,deleted_at FROM users")
    rooms = await conn.fetch("SELECT id,name,building,capacity,camera_id,camera_status FROM classrooms")
    exams = [dict(e) for e in await conn.fetch("SELECT id,course_code,course_name,department,classroom_id,room,scheduled_date,start_time,end_time,status,invigilator_id FROM exam_sessions WHERE scheduled_date IS NOT NULL")]
    users_email = {u["email"].casefold(): u for u in users}
    users_reg = {u["registration_or_employee_no"]: u for u in users}
    room_index: dict[str, list[Any]] = {}
    for room in rooms:
        room_index.setdefault(room["name"].casefold(), []).append(room)
    exam_index: dict[tuple, list[Any]] = {}
    for exam in exams:
        exam_index.setdefault(_exam_key(exam["course_code"], exam["scheduled_date"], exam["start_time"], exam["end_time"], exam["room"]), []).append(exam)
    rows: list[ImportRow] = []
    seen: dict[str, set[Any]] = {kind: set() for kind in HEADERS}
    # Dependencies are intentionally processed in this order, independent of multipart order.
    for kind in HEADERS:
        if kind not in files:
            continue
        try:
            parsed = parse_csv(kind, files[kind])
        except ValueError as exc:
            rows.append(ImportRow(kind, 1, "File", "error", str(exc)))
            continue
        for line, value in parsed:
            row = ImportRow(kind, line, value.get("full_name") or value.get("room_name") or value.get("course_code") or "Row")
            rows.append(row)
            try:
                if kind == "student_roster":
                    email = normalize_email(value["university_email"])
                    body = AdminCreateUserRequest(full_name=value["full_name"], email=email, role=Role.STUDENT, department=value["department"])
                    _validate_email_role_pairing(email, Role.STUDENT)
                    if value["student_reg_no"] != local_part_of(email):
                        raise ValueError("Registration number must match the six-digit university email local part.")
                    key = email
                    row.label = f"{body.full_name} · {value['student_reg_no']}"
                    row.values = {"full_name": body.full_name, "email":email, "department":body.department}
                    existing = users_email.get(email) or users_reg.get(value["student_reg_no"])
                    if existing is not None:
                        if (existing["deleted_at"] is not None or existing["status"] != "active" or existing["role"] != "student"
                                or existing["email"].casefold() != email or existing["registration_or_employee_no"] != value["student_reg_no"]):
                            raise ValueError("Account conflicts with an existing, disabled or deleted user. Use User Management.")
                        if existing["full_name"] != body.full_name or existing["department"] != body.department:
                            raise ValueError("Student already exists with different details. Update it through User Management.")
                        row.action, row.note, row.existing_id = "skip", "Student already exists; unchanged.", str(existing["id"])
                    else:
                        row.note = "Create student account; Google sign-in is still required for activation."
                elif kind == "classroom_inventory":
                    body = ClassroomCreate(name=value["room_name"], building=value["building"], capacity=int(value["capacity"]),
                                           camera_id=value["camera_id"] or None, camera_status=CameraStatus(value["camera_status"].lower()))
                    key = body.name.casefold()
                    row.values = body.model_dump(mode="json", exclude={"seat_map"})
                    matches = room_index.get(key, [])
                    if matches:
                        if len(matches) != 1:
                            raise ValueError("Room name is ambiguous; fix the existing classrooms first.")
                        existing = matches[0]
                        if any(existing[k] != row.values[k] for k in ("building", "capacity", "camera_id", "camera_status")):
                            raise ValueError("Classroom already exists with different details. Update it through Classroom Management.")
                        row.action, row.note, row.existing_id = "skip", "Classroom already exists; unchanged.", str(existing["id"])
                    else:
                        # Only a reference, not a fake DB id. Replaced by the actual id during commit.
                        room_index[key] = [{"id": None, "name":body.name}]
                        row.note = "Create classroom. Configure camera seat polygons separately."
                else:
                    day, start, end = _slot(value)
                    room_matches = room_index.get(value["room_name"].casefold(), [])
                    if len(room_matches) != 1:
                        raise ValueError("Room must match one existing classroom or a valid classroom in this batch.")
                    room = room_matches[0]
                    key = _exam_key(value["course_code"], day, start, end, value["room_name"])
                    row.values = {"course_code":value["course_code"].upper(), "date":day.isoformat(), "start_time":start.isoformat(),
                                  "end_time":end.isoformat(), "room_key":value["room_name"].casefold()}
                    row.label = f"{value['course_code'].upper()} · {day.isoformat()} · {value['start_time']} · {room['name']}"
                    matches = exam_index.get(key, [])
                    if len(matches)==1 and matches[0]["id"] is not None and matches[0]["classroom_id"] != room["id"]:
                        raise ValueError("Existing exam has a different or missing classroom link. Correct it through Exam Schedule.")
                    if kind == "exam_schedule":
                        body = ExamScheduleCreate(course_code=value["course_code"], course_name=value["course_name"], department=value["department"],
                                                  date=day,start_time=start,end_time=end,classroom_id=room["id"] or UUID(int=0))
                        row.values.update(course_name=body.course_name, department=body.department)
                        if matches:
                            if len(matches) != 1 or matches[0]["status"] != "scheduled":
                                raise ValueError("Matching exam is ambiguous or has already started, finished or been cancelled.")
                            existing = matches[0]
                            if existing["course_name"] != body.course_name or existing["department"] != body.department:
                                raise ValueError("Exam already exists with different details. Update it through Exam Schedule.")
                            row.action, row.note, row.existing_id = "skip", "Exam already exists; unchanged.", str(existing["id"])
                        else:
                            # Refuse room double-bookings in imports instead of silently producing a conflicting setup.
                            if any(e["status"] in ("scheduled","in_progress") and e["scheduled_date"] == day
                                   and e["room"].casefold() == value["room_name"].casefold()
                                   and e["start_time"] < end and start < e["end_time"] for e in exams):
                                raise ValueError("Room is already booked for an overlapping exam.")
                            planned = {"id":None,"classroom_id":room["id"],"course_code":body.course_code.upper(),"room":room["name"],"scheduled_date":day,
                                       "start_time":start,"end_time":end,"status":"scheduled","invigilator_id":None}
                            exams.append(planned)
                            exam_index[key] = [planned]
                    else:
                        if len(matches) != 1 or matches[0]["status"] != "scheduled":
                            raise ValueError("Match one scheduled exam using course, date, times and room; include its schedule CSV if it is new.")
                        exam = matches[0]
                        teacher = users_email.get(normalize_email(value["teacher_email"]))
                        if teacher is None or teacher["deleted_at"] is not None or teacher["role"] != "teacher" or teacher["status"] != "active":
                            raise ValueError("Teacher email must belong to a registered active teacher account.")
                        teacher_id = teacher["id"]
                        row.values["teacher_id"] = str(teacher_id)
                        row.values["exam_key"] = [value["course_code"].upper(),day.isoformat(),start.isoformat(),end.isoformat(),value["room_name"].casefold()]
                        row.values["previous_teacher_id"] = str(exam["invigilator_id"]) if exam["invigilator_id"] else None
                        if exam["invigilator_id"] == teacher_id:
                            row.action, row.note = "skip", "This teacher is already assigned; unchanged."
                        elif exam["invigilator_id"]:
                            raise ValueError("Exam already has a different invigilator. Change it through Assignments.")
                        elif any(e is not exam and e["invigilator_id"] == teacher_id and e["status"] in ("scheduled","in_progress")
                                 and e["scheduled_date"] == day and e["start_time"] < end and start < e["end_time"] for e in exams):
                            raise ValueError("Teacher is already invigilating an overlapping exam.")
                        else:
                            row.note = f"Assign {teacher['full_name']} and send the existing in-app notification."
                        row.existing_id = str(exam["id"]) if exam["id"] else None
                        exam["invigilator_id"] = teacher_id  # Include other assignment rows in clash checks.
                if key in seen[kind]:
                    raise ValueError("Duplicate record in this CSV. Remove the repeated row.")
                seen[kind].add(key)
            except ValidationError as exc:
                first = exc.errors()[0]
                _error(row, f"{'.'.join(str(v) for v in first['loc'])}: {first['msg']}")
            except HTTPException as exc:
                _error(row, str(exc.detail))
            except (ValueError, KeyError) as exc:
                _error(row, str(exc))
    digest_data = [{**row.public(),"values":row.values,"existing_id":row.existing_id} for row in rows]
    fingerprint = hashlib.sha256(json.dumps(digest_data,sort_keys=True,default=str).encode()).hexdigest()
    return ImportPlan(rows, fingerprint)


async def apply_plan(conn: asyncpg.Connection, plan: ImportPlan, actor: CurrentUser, request: Request) -> dict[str, int]:
    room_ids = {r["name"].casefold(): r["id"] for r in await conn.fetch("SELECT id,name FROM classrooms")}
    exam_ids = {_exam_key(e["course_code"],e["scheduled_date"],e["start_time"],e["end_time"],e["room"]): e["id"]
                for e in await conn.fetch("SELECT id,course_code,scheduled_date,start_time,end_time,room FROM exam_sessions WHERE scheduled_date IS NOT NULL")}
    created = {kind:0 for kind in HEADERS}
    for row in plan.rows:
        if row.action != "create":
            continue
        v = row.values
        if row.kind == "student_roster":
            await admin_create_user(AdminCreateUserRequest(**v,role=Role.STUDENT),request,actor,conn)
        elif row.kind == "classroom_inventory":
            result = await create_classroom(ClassroomCreate(**v),request,actor,conn)
            room_ids[v["name"].casefold()] = UUID(result.id)
        elif row.kind == "exam_schedule":
            result = await schedule_exam(ExamScheduleCreate(**{k:v[k] for k in ("course_code","course_name","department","date","start_time","end_time")},
                                                          classroom_id=room_ids[v["room_key"]]),request,actor,conn)
            key = _exam_key(v["course_code"],date.fromisoformat(v["date"]),time.fromisoformat(v["start_time"]),time.fromisoformat(v["end_time"]),v["room_key"])
            exam_ids[key] = UUID(result.id)
        else:
            key = _exam_key(v["course_code"],date.fromisoformat(v["date"]),time.fromisoformat(v["start_time"]),time.fromisoformat(v["end_time"]),v["room_key"])
            await assign_invigilator(exam_ids[key],AssignInvigilatorRequest(teacher_id=v["teacher_id"]),request,actor,conn)
        created[row.kind] += 1
    return created
