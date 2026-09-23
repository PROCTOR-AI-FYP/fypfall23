"""Google sign-in (via Supabase Auth) exchanged for the app's own session.

POST /api/auth/session  Supabase access token -> verified -> account lookup,
                        first-time activation or student auto-provisioning
                        -> app JWT in an httpOnly cookie
GET  /api/auth/me       who the session cookie belongs to (JS cannot read it)
POST /api/auth/logout   clears the cookie

Account rules, all decided here from the *verified* email, never from any
client hint:
  - the email must be on ALLOWED_EMAIL_DOMAIN
  - unknown + six-digit local part -> a student account is created
  - unknown + anything else        -> refused; staff are created by an Admin
  - known, not yet linked          -> linked to this Google identity (activation)
  - known, linked to this identity -> signed in
  - known, linked to another one   -> refused and audit-logged as a security
                                      event; never silently re-linked
"""
from __future__ import annotations

import uuid

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.audit import ACTION_SECURITY_RELINK_REJECTED, ACTION_SIGN_IN, ACTION_SIGN_OUT, record_audit
from app.config import settings
from app.deps import CurrentUser, get_client_ip, get_current_user, get_db, resolve_session_user
from app.models import Role, UserStatus
from app.schemas import SessionRequest, UserOut
from app.security import (
    clear_session_cookie,
    create_access_token,
    is_allowed_domain,
    is_student_shaped_local_part,
    local_part_of,
    normalize_email,
    set_session_cookie,
)
from app.services.users import USER_COLUMNS, fetch_user, row_to_user
from app.supabase_auth import SupabaseAuthUnavailable, SupabaseTokenError, verify_supabase_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

ERR_UNVERIFIED = "Your Google sign-in could not be verified. Please try again."
ERR_UNAVAILABLE = "Sign-in is temporarily unavailable. Please try again in a moment."
ERR_STAFF_NOT_PROVISIONED = (
    "This account must be created by an administrator before you can sign in. Contact your department."
)
ERR_DISABLED = "This account has been deactivated. Contact your department."
ERR_IDENTITY_CONFLICT = (
    "This account is linked to a different Google identity. Contact your administrator."
)


def _wrong_domain_message() -> str:
    return f"Sign in with your @{settings.allowed_email_domain} Google account."


class _Rejected(Exception):
    def __init__(self, code: int, detail: str, outcome: str, *, security_event: bool = False) -> None:
        self.code, self.detail, self.outcome, self.security_event = code, detail, outcome, security_event


async def _provision_student(conn: asyncpg.Connection, *, email: str, sub: str, full_name: str | None) -> asyncpg.Record:
    reg_no = local_part_of(email)
    try:
        row = await conn.fetchrow(
            f"""
            INSERT INTO users (full_name, email, role, registration_or_employee_no, supabase_user_id, auth_provider)
            VALUES ($1, $2, 'student', $3, $4::uuid, 'google')
            RETURNING {USER_COLUMNS}, supabase_user_id, deleted_at
            """,
            full_name or reg_no,
            email,
            reg_no,
            sub,
        )
    except asyncpg.UniqueViolationError as exc:
        # Either this Google identity is already linked to another account, or
        # the registration number is held by an existing (differently emailed)
        # row. Both mean an identity/record conflict, not a new student.
        raise _Rejected(status.HTTP_403_FORBIDDEN, ERR_IDENTITY_CONFLICT, "identity_conflict", security_event=True) from exc
    return row


async def _resolve_account(conn: asyncpg.Connection, *, email: str, sub: str, full_name: str | None) -> tuple[asyncpg.Record, str]:
    """Returns (user row, outcome) or raises _Rejected. Runs inside a transaction."""
    row = await conn.fetchrow(
        f"SELECT {USER_COLUMNS}, supabase_user_id, deleted_at FROM users WHERE lower(email) = $1 FOR UPDATE",
        email,
    )

    if row is None:
        if not is_student_shaped_local_part(local_part_of(email)):
            raise _Rejected(status.HTTP_403_FORBIDDEN, ERR_STAFF_NOT_PROVISIONED, "staff_not_provisioned")
        return await _provision_student(conn, email=email, sub=sub, full_name=full_name), "student_provisioned"

    if row["deleted_at"] is not None or row["status"] != UserStatus.ACTIVE.value:
        raise _Rejected(status.HTTP_403_FORBIDDEN, ERR_DISABLED, "account_disabled")

    linked = row["supabase_user_id"]
    if linked is None:
        try:
            activated = await conn.fetchrow(
                f"""
                UPDATE users SET supabase_user_id = $1::uuid, auth_provider = 'google'
                WHERE id = $2 AND supabase_user_id IS NULL
                RETURNING {USER_COLUMNS}, supabase_user_id, deleted_at
                """,
                sub,
                row["id"],
            )
        except asyncpg.UniqueViolationError as exc:
            # This Google identity already belongs to a different account.
            raise _Rejected(
                status.HTTP_403_FORBIDDEN, ERR_IDENTITY_CONFLICT, "identity_conflict", security_event=True
            ) from exc
        return activated, "account_activated"

    if str(linked) != sub:
        raise _Rejected(status.HTTP_403_FORBIDDEN, ERR_IDENTITY_CONFLICT, "relink_rejected", security_event=True)
    return row, "signed_in"


@router.post("/session", response_model=UserOut)
async def create_session(
    body: SessionRequest,
    request: Request,
    response: Response,
    conn: asyncpg.Connection = Depends(get_db),
) -> UserOut:
    ip = get_client_ip(request)

    try:
        identity = await verify_supabase_token(body.supabase_access_token)
    except SupabaseAuthUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_UNAVAILABLE) from exc
    except SupabaseTokenError as exc:
        await record_audit(
            conn, actor_id=None, action=ACTION_SIGN_IN, target="unverified-token",
            new_value={"outcome": "invalid_token", "reason": str(exc)}, ip_address=ip,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_UNVERIFIED) from exc

    email = normalize_email(identity.email)
    try:
        sub = str(uuid.UUID(identity.sub))
    except ValueError:
        sub = ""
    if not sub:
        await record_audit(
            conn, actor_id=None, action=ACTION_SIGN_IN, target=email,
            new_value={"outcome": "invalid_token", "reason": "sub_not_uuid"}, ip_address=ip,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_UNVERIFIED)

    if not is_allowed_domain(email):
        await record_audit(
            conn, actor_id=None, action=ACTION_SIGN_IN, target=email,
            new_value={"outcome": "wrong_domain"}, ip_address=ip,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_wrong_domain_message())

    try:
        async with conn.transaction():
            row, outcome = await _resolve_account(conn, email=email, sub=sub, full_name=identity.full_name)
    except _Rejected as rejection:
        await record_audit(
            conn,
            actor_id=None,
            action=ACTION_SECURITY_RELINK_REJECTED if rejection.security_event else ACTION_SIGN_IN,
            target=email,
            new_value={"outcome": rejection.outcome, "presented_sub": sub},
            ip_address=ip,
        )
        raise HTTPException(status_code=rejection.code, detail=rejection.detail) from rejection

    user = row_to_user(row)
    await record_audit(
        conn, actor_id=user.id, action=ACTION_SIGN_IN, target=email, new_value={"outcome": outcome}, ip_address=ip
    )
    # Role comes from the row just read/written in this request.
    set_session_cookie(response, create_access_token(user_id=user.id, role=Role(row["role"])))
    return user


@router.get("/me", response_model=UserOut)
async def me(
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
) -> UserOut:
    user = await fetch_user(conn, current_user.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This account is no longer active")
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, conn: asyncpg.Connection = Depends(get_db)) -> Response:
    # Works with an expired or invalid cookie too: signing out must always succeed.
    try:
        user = await resolve_session_user(conn, request.cookies.get(settings.session_cookie_name))
    except HTTPException:
        user = None
    if user is not None:
        await record_audit(
            conn, actor_id=user.user_id, action=ACTION_SIGN_OUT, target=user.user_id,
            new_value={}, ip_address=get_client_ip(request),
        )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response
