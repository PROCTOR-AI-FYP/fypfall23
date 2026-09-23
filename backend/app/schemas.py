"""Pydantic v2 request/response models.

Request models use extra="forbid": an unexpected field (a client-supplied
role on a path that must derive it, a leftover password field) is a 422,
never silently accepted. Response models never carry password_hash or
supabase_user_id; account activation is exposed only as a boolean.
"""
from __future__ import annotations

from datetime import date as Date, datetime, time
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    AlertStatus,
    AppealStatus,
    BehaviourType,
    CameraStatus,
    CaseStatus,
    ClipStatus,
    ExamSessionStatus,
    NoticeSource,
    NotificationType,
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
    """What the detection worker gets back from POST /internal/detections."""

    id: str
    session_id: str
    seat_number: int
    student_id: str | None
    reference_no: str
    status: CaseStatus
    created_at: datetime


# --- Classrooms ---


class SeatVertex(StrictModel):
    x: float = Field(ge=0, le=10000)
    y: float = Field(ge=0, le=10000)


class SeatPolygon(StrictModel):
    seat_number: int = Field(ge=1, le=1000)
    vertices: list[SeatVertex] = Field(min_length=3, max_length=64)


def _unique_seats(seat_map: list[SeatPolygon] | None) -> list[SeatPolygon] | None:
    if seat_map is not None:
        numbers = [seat.seat_number for seat in seat_map]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Each seat number may appear only once in the seat map.")
    return seat_map


SeatMap = Annotated[list[SeatPolygon], Field(max_length=1000), AfterValidator(_unique_seats)]
RoomName = Annotated[str, Field(min_length=1, max_length=60)]
Building = Annotated[str, Field(min_length=1, max_length=120)]
Capacity = Annotated[int, Field(ge=1, le=1000)]
CameraId = Annotated[str, Field(max_length=60)]


class ClassroomCreate(StrictModel):
    name: RoomName
    building: Building
    capacity: Capacity
    camera_id: CameraId | None = None
    camera_status: CameraStatus = CameraStatus.OFFLINE
    seat_map: SeatMap | None = None


class ClassroomUpdate(StrictModel):
    name: RoomName | None = None
    building: Building | None = None
    capacity: Capacity | None = None
    camera_id: CameraId | None = None
    camera_status: CameraStatus | None = None
    seat_map: SeatMap | None = None


class ClassroomOut(BaseModel):
    id: str
    name: str
    building: str
    capacity: int
    camera_id: str | None
    camera_status: CameraStatus
    seat_map: list[SeatPolygon] | None
    created_at: datetime


# --- Exam sessions and scheduling ---


class ExamSessionOut(BaseModel):
    id: str
    course_code: str
    course_name: str
    department: str
    classroom_id: str | None
    classroom_name: str
    scheduled_date: Date | None
    start_time: str | None  # "HH:MM"
    end_time: str | None
    status: ExamSessionStatus
    invigilator_id: str | None
    invigilator_name: str | None
    silent_mode: bool
    total_seats: int
    occupied_seats: int
    alert_count: int
    case_count: int
    confirmed_case_count: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


CourseCode = Annotated[str, Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9][A-Za-z0-9 -]*$")]
CourseName = Annotated[str, Field(min_length=1, max_length=200)]


class ExamScheduleCreate(StrictModel):
    course_code: CourseCode
    course_name: CourseName
    department: Department = ""
    date: Date
    start_time: time
    end_time: time
    classroom_id: UUID


class ExamScheduleUpdate(StrictModel):
    course_code: CourseCode | None = None
    course_name: CourseName | None = None
    department: Department | None = None
    date: Date | None = None
    start_time: time | None = None
    end_time: time | None = None
    classroom_id: UUID | None = None


class ExamScheduleOut(BaseModel):
    id: str
    course_code: str
    course_name: str
    department: str
    date: Date | None
    start_time: str | None
    end_time: str | None
    classroom_id: str | None
    classroom_name: str
    invigilator_id: str | None
    invigilator_name: str | None
    status: ExamSessionStatus
    has_conflict: bool
    conflict_details: str | None


class AssignInvigilatorRequest(StrictModel):
    teacher_id: UUID


class InvigilatorAssignmentOut(BaseModel):
    id: str
    exam_id: str
    teacher_id: str
    teacher_name: str
    department: str
    course_code: str
    date: Date | None
    start_time: str | None
    end_time: str | None
    classroom_name: str
    status: str = "Assigned"


# --- Alerts (detections, from the invigilator's side) ---


class DetectionOut(BaseModel):
    id: str
    session_id: str
    case_id: str | None
    seat_number: int
    student_id: str | None
    student_name: str | None
    behaviour_types: list[BehaviourType]
    per_signal: dict[BehaviourType, float]
    composite_score: float
    detected_at: datetime
    status: AlertStatus


Note = Annotated[str, Field(max_length=2000)]


class AlertConfirmRequest(StrictModel):
    teacher_note: Note | None = None


class AlertDismissRequest(StrictModel):
    note: Note | None = None


# --- Case detail, penalties, appeals ---


class TimelineEntryOut(BaseModel):
    id: str
    action: str
    actor_name: str
    actor_role: Role | None
    details: str | None
    timestamp: datetime


class PenaltySummaryOut(BaseModel):
    """A penalty as embedded in a case (no notice text)."""

    id: str
    case_id: str
    penalty_type: PenaltyType
    description: str
    issued_by: str
    issued_by_name: str
    notice_reference: str
    revoked_at: datetime | None
    created_at: datetime


class AppealOut(BaseModel):
    id: str
    case_id: str
    case_reference_no: str
    student_id: str
    student_name: str
    student_reg_no: str
    statement: str
    supporting_info: str | None
    status: AppealStatus
    reviewed_by: str | None
    reviewer_name: str | None
    review_note: str | None
    submitted_at: datetime
    resolved_at: datetime | None


class CaseDetailOut(BaseModel):
    id: str
    reference_no: str
    session_id: str
    student_id: str | None
    student_name: str | None
    student_reg_no: str | None
    course_code: str
    course_name: str
    classroom_name: str
    seat_number: int
    behaviour_types: list[BehaviourType]
    composite_score: float
    status: CaseStatus
    detection_event_id: str | None
    teacher_note: str | None
    teacher_id: str | None
    teacher_name: str | None
    penalty: PenaltySummaryOut | None
    appeal: AppealOut | None
    timeline: list[TimelineEntryOut]
    created_at: datetime
    updated_at: datetime


class AppealCreate(StrictModel):
    statement: str = Field(min_length=1, max_length=5000)
    supporting_info: str | None = Field(default=None, max_length=1000)


class AppealResolve(StrictModel):
    status: AppealStatus
    review_note: str = Field(min_length=1, max_length=4000)


# --- Notifications ---


class NotificationOut(BaseModel):
    id: str
    type: NotificationType
    title: str
    message: str
    reference_type: str | None
    reference_id: str | None
    read: bool
    created_at: datetime


# --- Admin configuration and reporting ---


class ThresholdIn(StrictModel):
    behaviour_type: BehaviourType
    sensitivity: int = Field(ge=0, le=100)
    weight: float = Field(ge=0.0, le=1.0)


def _one_per_behaviour(configs: list[ThresholdIn]) -> list[ThresholdIn]:
    if sorted(c.behaviour_type.value for c in configs) != sorted(b.value for b in BehaviourType):
        raise ValueError("Provide exactly one threshold for each of the five behaviour types.")
    return configs


ThresholdSet = Annotated[list[ThresholdIn], AfterValidator(_one_per_behaviour)]


class ThresholdOut(BaseModel):
    behaviour_type: BehaviourType
    sensitivity: int
    weight: float
    updated_at: datetime
    updated_by_name: str | None


class AuditLogEntryOut(BaseModel):
    id: str
    timestamp: datetime
    user_id: str | None
    user_name: str
    user_role: Role | None
    action: str
    action_code: str
    target: str
    details: str
    ip_address: str | None


class CountByLabel(BaseModel):
    label: str
    count: int


class StatisticsOut(BaseModel):
    incidents_by_department: list[CountByLabel]
    incidents_over_time: list[CountByLabel]  # label = ISO date
    behavior_distribution: list[CountByLabel]  # label = BehaviourType value
    case_status_distribution: list[CountByLabel]  # label = CaseStatus value
    total_cases: int
    total_appeals: int
    appeal_success_rate: float
    average_resolution_days: float


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


class CaseTransitionRequest(StrictModel):
    to_status: CaseStatus
    note: Note | None = None


class PenaltyRequest(StrictModel):
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
    """A penalty with its generated notice (HOD endpoints only)."""

    id: str
    case_id: str
    penalty_type: PenaltyType
    description: str
    issued_by: str
    issued_by_name: str
    notice_reference: str
    notice_document: str | None
    notice_source: NoticeSource | None
    revoked_at: datetime | None
    created_at: datetime
