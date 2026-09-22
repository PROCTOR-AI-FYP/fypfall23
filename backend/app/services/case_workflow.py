"""Case status state machine and who may drive each transition."""
from __future__ import annotations

from app.models import CaseStatus, Role

ALLOWED_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.PENDING_REVIEW: frozenset({CaseStatus.CONFIRMED, CaseStatus.DISMISSED, CaseStatus.ESCALATED}),
    CaseStatus.ESCALATED: frozenset({CaseStatus.CONFIRMED, CaseStatus.DISMISSED}),
    CaseStatus.CONFIRMED: frozenset(),
    CaseStatus.DISMISSED: frozenset(),
}

# Teachers triage fresh cases; anything escalated is the HOD's decision.
ACTIONABLE_FROM: dict[Role, frozenset[CaseStatus]] = {
    Role.TEACHER: frozenset({CaseStatus.PENDING_REVIEW}),
    Role.HOD: frozenset({CaseStatus.PENDING_REVIEW, CaseStatus.ESCALATED}),
}


class TransitionNotAllowed(Exception):
    def __init__(self, detail: str, *, forbidden: bool) -> None:
        super().__init__(detail)
        self.detail = detail
        self.forbidden = forbidden


def check_transition(*, role: Role, current: CaseStatus, target: CaseStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise TransitionNotAllowed(f"A case cannot move from {current.value} to {target.value}.", forbidden=False)
    if current not in ACTIONABLE_FROM.get(role, frozenset()):
        raise TransitionNotAllowed("Your role cannot act on a case in this status.", forbidden=True)
