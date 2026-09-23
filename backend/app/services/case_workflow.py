"""Case status state machine and who may drive each transition.

  pending_review -> confirmed | dismissed | escalated   (teacher of the session, or HOD)
  escalated      -> confirmed | dismissed               (HOD only)
  confirmed, dismissed                                  terminal for check_transition
  A penalty may only be issued on a confirmed case (routers/cases.py).

The one way out of `confirmed` is not a status change anyone can request: an
HOD accepting the student's appeal dismisses the case (check_appeal_exit,
used only by routers/appeals.py). Nothing ever leaves `dismissed`.
"""
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

APPEAL_EXIT = (CaseStatus.CONFIRMED, CaseStatus.DISMISSED)


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


def check_appeal_exit(*, role: Role, current: CaseStatus) -> None:
    if role != Role.HOD:
        raise TransitionNotAllowed("Only the Head of Department resolves appeals.", forbidden=True)
    if current != APPEAL_EXIT[0]:
        raise TransitionNotAllowed(f"An appeal can only overturn a confirmed case, not a {current.value} one.", forbidden=False)
