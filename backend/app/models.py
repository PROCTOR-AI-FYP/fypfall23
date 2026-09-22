"""Domain enums, kept consistent with AGENTS.md's data contracts."""
from __future__ import annotations

import re
from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    HOD = "hod"
    TEACHER = "teacher"
    EXAM_CONTROLLER = "exam_controller"
    STUDENT = "student"


STAFF_ROLES = {Role.ADMIN, Role.HOD, Role.TEACHER, Role.EXAM_CONTROLLER}


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class CaseStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"


class ExamSessionStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SeatmapRowStatus(str, Enum):
    RESOLVED = "Resolved"
    UNREGISTERED_ID = "Unregistered ID"
    UNVERIFIED = "Unverified"


class BehaviourType(str, Enum):
    """Wire values match the detection event contract in AGENTS.md section 6."""

    GAZE_DEVIATION = "GAZE_DEVIATION"
    HEAD_POSE_VIOLATION = "HEAD_POSE_VIOLATION"
    LIP_MOVEMENT = "LIP_MOVEMENT"
    PHONE_DETECTED = "PHONE_DETECTED"
    UNAUTHORISED_OBJECT = "UNAUTHORISED_OBJECT"


class PenaltyType(str, Enum):
    FORMAL_WARNING = "formal_warning"
    MARK_DEDUCTION = "mark_deduction"
    EXAM_VOIDANCE = "exam_voidance"
    DISCIPLINARY_REFERRAL = "disciplinary_referral"
    SUSPENSION = "suspension"
    OTHER = "other"


class ClipStatus(str, Enum):
    PENDING_UPLOAD = "pending_upload"
    AVAILABLE = "available"
    DELETED_AFTER_REVIEW = "deleted_after_review"


class NoticeSource(str, Enum):
    ANTHROPIC = "anthropic"
    TEMPLATE = "template"


# Local part of a student email must be exactly six digits (registration number).
STUDENT_LOCAL_PART_RE = re.compile(r"^\d{6}$")
