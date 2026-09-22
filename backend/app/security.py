"""Password hashing, JWT issuance/verification, and email-derived role logic.

This module is the single place that decides what role an account gets from
its email — routers must never accept a client-supplied role for the
self-service path (see AGENTS.md / spec section 1).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import settings
from app.models import STUDENT_LOCAL_PART_RE, Role

JWT_SUBJECT_CLAIM = "sub"
JWT_ROLE_CLAIM = "role"
JWT_EXPIRY_CLAIM = "exp"


def hash_password(raw_password: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(raw_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(raw_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash in storage; never treat as a match.
        return False


def local_part_of(email: str) -> str:
    return email.split("@", 1)[0]


def email_domain_of(email: str) -> str:
    parts = email.split("@", 1)
    return parts[1] if len(parts) == 2 else ""


def is_allowed_domain(email: str) -> bool:
    return email_domain_of(email).lower() == settings.allowed_email_domain.lower()


def is_student_shaped_local_part(local_part: str) -> bool:
    """True if the local part is exactly six digits -> a registration number."""
    return bool(STUDENT_LOCAL_PART_RE.match(local_part))


def derive_role_for_signup(email: str) -> tuple[Role, str] | None:
    """Self-service signup path: only ever returns (Role.STUDENT, reg_no) or None.

    Returns None if the local part is not six digits, meaning this email
    cannot self-register (spec section 1, step 2).
    """
    local_part = local_part_of(email)
    if is_student_shaped_local_part(local_part):
        return Role.STUDENT, local_part
    return None


def generate_verification_token() -> str:
    return secrets.token_urlsafe(settings.verification_token_bytes)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def hash_email_for_rate_limit(email: str) -> str:
    return hashlib.sha256(email.lower().encode("utf-8")).hexdigest()


def verification_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=settings.verification_token_ttl_hours)


def create_access_token(*, user_id: str, role: Role) -> str:
    """Issue a JWT whose role claim comes from the caller's argument only.

    Callers (routers/auth.py::login) must always pass a role value that was
    just read fresh from the users table — never a cached or client-supplied
    value — so the claim reflects the account's true, current role.
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
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
