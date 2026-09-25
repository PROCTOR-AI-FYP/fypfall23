"""App session JWTs, the session cookie, and email-derived role logic.

This module is the single place that decides what role a self-provisioned
account gets from its email: only a six-digit local part (a registration
number) is ever auto-provisioned, and only as a student. Staff roles come
exclusively from an Admin (routers/admin_users.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Response

from app.config import settings
from app.models import STUDENT_LOCAL_PART_RE, Role

JWT_SUBJECT_CLAIM = "sub"
JWT_ROLE_CLAIM = "role"
JWT_EXPIRY_CLAIM = "exp"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def local_part_of(email: str) -> str:
    return email.split("@", 1)[0]


def email_domain_of(email: str) -> str:
    parts = email.split("@", 1)
    return parts[1] if len(parts) == 2 else ""


def is_allowed_domain(email: str) -> bool:
    domain = email_domain_of(email).lower()
    return domain in settings.allowed_email_domains


def is_student_domain(email: str) -> bool:
    """True if the email is on the student-specific domain."""
    return email_domain_of(email).lower() == settings.student_email_domain.lower()


def is_student_shaped_local_part(local_part: str) -> bool:
    """True if the local part is exactly six digits -> a registration number."""
    return bool(STUDENT_LOCAL_PART_RE.match(local_part))


def create_access_token(*, user_id: str, role: Role) -> str:
    """Issue the app's own session JWT.

    The role claim is informational only: deps.get_current_user re-reads the
    role (and account status) from the users table on every request.
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        JWT_SUBJECT_CLAIM: user_id,
        JWT_ROLE_CLAIM: role.value,
        "iat": now,
        JWT_EXPIRY_CLAIM: now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": [JWT_SUBJECT_CLAIM, JWT_EXPIRY_CLAIM, "iat"]},
    )


def _cookie_attributes() -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": settings.session_cookie_secure,
        "samesite": settings.session_cookie_samesite,
        "domain": settings.session_cookie_domain or None,
        "path": "/",
    }


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name, token, max_age=settings.jwt_expire_minutes * 60, **_cookie_attributes()
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, **_cookie_attributes())
