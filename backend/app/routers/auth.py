"""Self-service auth endpoints: signup, email verification, resend, login.

Every code path here follows spec section 1's rule: the client never sets a
role. Signup's Pydantic model has no `role` field (extra="ignore"), and the
only role signup can ever assign is Role.STUDENT, derived from the email's
six-digit local part.
"""
from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import (
    ACTION_LOGIN_ATTEMPT,
    ACTION_RESEND_VERIFICATION_ATTEMPT,
    ACTION_SIGNUP_ATTEMPT,
    ACTION_VERIFY_EMAIL_ATTEMPT,
    record_audit,
)
from app.config import settings
from app.deps import get_client_ip, get_db
from app.email import get_email_sender
from app.models import Role
from app.redis_client import increment_and_check_limit
from app.schemas import (
    LoginRequest,
    LoginResponse,
    ResendVerificationRequest,
    SignupRequest,
    SignupResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.security import (
    create_access_token,
    derive_role_for_signup,
    generate_verification_token,
    hash_password,
    hash_email_for_rate_limit,
    hash_token,
    is_allowed_domain,
    verification_token_expiry,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

ERR_NON_UNIVERSITY_EMAIL = "Please sign up with your university email."
ERR_STAFF_LOCAL_PART = "This account type is created by an administrator — contact your department."
ERR_RATE_LIMITED = "Too many requests. Please try again later."
ERR_INVALID_CREDENTIALS = "Invalid email or password."
ERR_EMAIL_NOT_VERIFIED = "Please verify your email before signing in — resend link"
ERR_INVALID_VERIFICATION = "Invalid or expired verification link."

GENERIC_SIGNUP_MESSAGE = "If this email is valid, a verification link has been sent."

# A syntactically valid bcrypt hash of a value nobody can produce, used to
# keep login's timing similar when no user row exists at all.
_DUMMY_PASSWORD_HASH = "$2b$12$C6UzMDM.H6dfI/f3IKxGGO5/y5vY0f7YHf5c5c5c5c5c5c5c5c5c5C"


def _reject_if_not_student_signup_eligible(email: str) -> None:
    if not is_allowed_domain(email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERR_NON_UNIVERSITY_EMAIL)
    if derive_role_for_signup(email) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERR_STAFF_LOCAL_PART)


async def _enforce_signup_rate_limit(*, prefix: str, ip: str, email: str) -> None:
    ip_ok = await increment_and_check_limit(
        key=f"{prefix}:ip:{ip}",
        limit=settings.signup_ip_limit,
        window_seconds=settings.signup_rate_limit_window_seconds,
    )
    email_ok = await increment_and_check_limit(
        key=f"{prefix}:email:{hash_email_for_rate_limit(email)}",
        limit=settings.signup_email_limit,
        window_seconds=settings.signup_rate_limit_window_seconds,
    )
    if not ip_ok or not email_ok:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=ERR_RATE_LIMITED)


async def _issue_verification_token(conn: asyncpg.Connection, *, user_id: str, email: str, full_name: str) -> None:
    raw_token = generate_verification_token()
    await conn.execute(
        """
        INSERT INTO email_verifications (user_id, token_hash, expires_at)
        VALUES ($1, $2, $3)
        """,
        user_id,
        hash_token(raw_token),
        verification_token_expiry(),
    )
    verification_link = f"{settings.frontend_url}/verify-email?token={raw_token}"
    await get_email_sender().send_verification_email(
        to_address=email, full_name=full_name, verification_link=verification_link
    )


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_202_ACCEPTED)
async def signup(
    body: SignupRequest,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
) -> SignupResponse:
    ip = get_client_ip(request)
    _reject_if_not_student_signup_eligible(body.email)
    await _enforce_signup_rate_limit(prefix="signup", ip=ip, email=body.email)

    derived = derive_role_for_signup(body.email)
    assert derived is not None  # guaranteed by _reject_if_not_student_signup_eligible
    role, registration_no = derived

    outcome = "unknown"
    existing = await conn.fetchrow(
        "SELECT id, email_verified, full_name FROM users WHERE email = $1", body.email
    )
    if existing is None:
        try:
            new_user = await conn.fetchrow(
                """
                INSERT INTO users (full_name, email, password_hash, role, registration_or_employee_no, status, email_verified)
                VALUES ($1, $2, $3, $4, $5, 'active', false)
                RETURNING id
                """,
                body.full_name,
                body.email,
                hash_password(body.password),
                role.value,
                registration_no,
            )
        except asyncpg.UniqueViolationError:
            # Lost a race with a concurrent signup/admin-create for the same
            # email or reg. no. Treat identically to "already exists".
            outcome = "already_existed_race"
        else:
            await _issue_verification_token(
                conn, user_id=str(new_user["id"]), email=body.email, full_name=body.full_name
            )
            outcome = "created_new_account"
    elif not existing["email_verified"]:
        await _issue_verification_token(
            conn, user_id=str(existing["id"]), email=body.email, full_name=existing["full_name"]
        )
        outcome = "resent_to_existing_unverified"
    else:
        outcome = "already_verified_noop"

    await record_audit(
        conn,
        actor_id=None,
        action=ACTION_SIGNUP_ATTEMPT,
        target=body.email,
        new_value={"outcome": outcome},
        ip_address=ip,
    )
    return SignupResponse(message=GENERIC_SIGNUP_MESSAGE)


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
) -> VerifyEmailResponse:
    token_hash = hash_token(body.token)
    row = await conn.fetchrow(
        "SELECT id, user_id, expires_at, consumed_at FROM email_verifications WHERE token_hash = $1",
        token_hash,
    )

    is_valid = (
        row is not None
        and row["consumed_at"] is None
        and row["expires_at"] > datetime.now(timezone.utc)
    )

    if not is_valid:
        await record_audit(
            conn,
            actor_id=None,
            action=ACTION_VERIFY_EMAIL_ATTEMPT,
            target=body.token[:8] + "...",
            new_value={"outcome": "invalid_or_expired_or_consumed"},
            ip_address=get_client_ip(request),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ERR_INVALID_VERIFICATION)

    async with conn.transaction():
        await conn.execute(
            "UPDATE email_verifications SET consumed_at = now() WHERE id = $1", row["id"]
        )
        await conn.execute(
            "UPDATE users SET email_verified = true WHERE id = $1", row["user_id"]
        )

    await record_audit(
        conn,
        actor_id=str(row["user_id"]),
        action=ACTION_VERIFY_EMAIL_ATTEMPT,
        target=str(row["user_id"]),
        new_value={"outcome": "verified"},
        ip_address=get_client_ip(request),
    )
    return VerifyEmailResponse(message="Email verified. You can now sign in.")


@router.post("/resend-verification", response_model=SignupResponse, status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
) -> SignupResponse:
    ip = get_client_ip(request)
    _reject_if_not_student_signup_eligible(body.email)
    await _enforce_signup_rate_limit(prefix="resend", ip=ip, email=body.email)

    outcome = "no_matching_unverified_account"
    existing = await conn.fetchrow(
        "SELECT id, email_verified, full_name FROM users WHERE email = $1", body.email
    )
    if existing is not None and not existing["email_verified"]:
        await _issue_verification_token(
            conn, user_id=str(existing["id"]), email=body.email, full_name=existing["full_name"]
        )
        outcome = "resent"

    await record_audit(
        conn,
        actor_id=None,
        action=ACTION_RESEND_VERIFICATION_ATTEMPT,
        target=body.email,
        new_value={"outcome": outcome},
        ip_address=ip,
    )
    return SignupResponse(message=GENERIC_SIGNUP_MESSAGE)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
) -> LoginResponse:
    ip = get_client_ip(request)
    user = await conn.fetchrow(
        "SELECT id, password_hash, role, email_verified FROM users WHERE email = $1", body.email
    )

    password_hash = user["password_hash"] if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(body.password, password_hash) and user is not None

    if not password_ok:
        await record_audit(
            conn,
            actor_id=None,
            action=ACTION_LOGIN_ATTEMPT,
            target=body.email,
            new_value={"outcome": "invalid_credentials"},
            ip_address=ip,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_INVALID_CREDENTIALS)

    if not user["email_verified"]:
        await record_audit(
            conn,
            actor_id=str(user["id"]),
            action=ACTION_LOGIN_ATTEMPT,
            target=body.email,
            new_value={"outcome": "email_not_verified"},
            ip_address=ip,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERR_EMAIL_NOT_VERIFIED)

    # Role is read fresh from the row just fetched in this request — never
    # cached, never client-supplied.
    role = Role(user["role"])
    token = create_access_token(user_id=str(user["id"]), role=role)

    await record_audit(
        conn,
        actor_id=str(user["id"]),
        action=ACTION_LOGIN_ATTEMPT,
        target=body.email,
        new_value={"outcome": "success"},
        ip_address=ip,
    )
    return LoginResponse(access_token=token, role=role)
