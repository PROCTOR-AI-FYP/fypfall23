"""Pydantic v2 request/response models.

Request models use extra="forbid": an unexpected field (a client-supplied
role on a path that must derive it, a leftover password field) is a 422,
never silently accepted. Response models never carry password_hash or
supabase_user_id; account activation is exposed only as a boolean.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    BehaviourType,
    CaseStatus,
    ClipStatus,
    ExamSessionStatus,
    NoticeSource,
    PenaltyType,
    Role,
    SeatmapRowStatus,
    UserStatus,
)

Score = Annotated[float, Field(ge=0.0, le=1.0)]
FullName = Annotated[str, Field(min_length=1, max_length=200)]
Department = Annotated[str, Field(max_length=120)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Auth ---


class SessionRequest(StrictModel):
    # A Supabase access token is a JWT of a few hundred bytes to ~2 KB.
    supabase_access_token: str = Field(min_length=1, max_length=8192)


class UserOut(BaseModel):
    id: str
    full_name: str
    email: str
    role: Role
    department: str
    registration_or_employee_no: str
    status: UserStatus
    # True once the account's owner has signed in with Google at least once.
    activated: bool
    created_at: datetime


class AdminCreateUserRequest(StrictModel):
    full_name: FullName
    email: EmailStr
    role: Role
    department: Department = ""
    status: UserStatus = UserStatus.ACTIVE


class AdminUpdateUserRequest(StrictModel):
    full_name: FullName | None = None
    email: EmailStr | None = None
    role: Role | None = None
    department: Department | None = None
    status: UserStatus | None = None


class SeatmapRowResult(BaseModel):
    seat_number: int
    student_reg_no: str
    status: SeatmapRowStatus


class SeatmapUploadResponse(BaseModel):
    rows: list[SeatmapRowResult]
    resolved_count: int
    rejected_count: int


class CaseOut(BaseModel):
    id: str
    session_id: str
    seat_number: int
    student_id: str | None
    reference_no: str
    status: CaseStatus
    created_at: datetime


class ExamSessionOut(BaseModel):
    id: str
    course_code: str
    room: str
    status: ExamSessionStatus


# --- Detection worker (internal) ---


class SeatFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat_number: int = Field(ge=1, le=1000)
    signals: dict[BehaviourType, Score] = Field(max_length=len(BehaviourType))


class FrameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    frame_index: int = Field(ge=0)
    seats: list[SeatFrame] = Field(max_length=500)


class TriggeredSeatOut(BaseModel):
    seat_number: int
    behaviour_types: list[BehaviourType]
    per_signal: dict[BehaviourType, float]
    composite_score: float


class FrameResponse(BaseModel):
    triggered: list[TriggeredSeatOut]


class DetectionEventIn(BaseModel):
    """The core detection event shape from AGENTS.md section 6."""

    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    seat_number: int = Field(ge=1, le=1000)
    behaviour_types: list[BehaviourType] = Field(min_length=1, max_length=len(BehaviourType))
    per_signal: dict[BehaviourType, Score]
    composite_score: Score
    snapshot_path: str = Field(max_length=300)
    detected_at: datetime


# --- Case workflow ---


class CaseTransitionRequest(BaseModel):
    to_status: CaseStatus
    note: str | None = Field(default=None, max_length=2000)


class PenaltyRequest(BaseModel):
    penalty_type: PenaltyType
    description: str = Field(min_length=1, max_length=4000)


class ClipStoredOut(BaseModel):
    detection_id: str
    duration_seconds: float
    original_bytes: int
    stored_bytes: int


class MediaClipOut(BaseModel):
    url: str
    expires_in_seconds: int
    duration_seconds: float
    size_bytes: int
    content_type: str = "video/mp4"


class CaseMediaOut(BaseModel):
    case_id: str | None
    detection_id: str
    clip_status: ClipStatus
    clip: MediaClipOut | None
    record_image_url: str | None
    snapshot_url: str | None
    clip_deleted_at: datetime | None


class PenaltyOut(BaseModel):
    id: str
    case_id: str
    penalty_type: PenaltyType
    description: str
    notice_reference: str
    notice_document: str | None
    notice_source: NoticeSource | None
    created_at: datetime
