"""Object-level authorization rules shared by REST routes and Socket.IO."""
from __future__ import annotations

from app.models import Role

SESSION_OVERSIGHT_ROLES = frozenset({Role.ADMIN, Role.HOD, Role.EXAM_CONTROLLER})


def can_review_evidence(*, role: Role, user_id: str, invigilator_id: str | None) -> bool:
    """Evidence clips go to the people in the review chain: the HOD and the invigilating teacher."""
    if role == Role.HOD:
        return True
    return role == Role.TEACHER and invigilator_id is not None and invigilator_id == user_id


def can_access_session(*, role: Role, user_id: str, invigilator_id: str | None) -> bool:
    """Oversight roles see every session; a teacher only the ones they invigilate."""
    if role in SESSION_OVERSIGHT_ROLES:
        return True
    return role == Role.TEACHER and invigilator_id is not None and invigilator_id == user_id
