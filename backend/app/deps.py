"""FastAPI dependencies: client IP, DB connections (plain and RLS-scoped),
and the cookie-authenticated current user / role gates.
"""
from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

import asyncpg
import jwt
from fastapi import Depends, Header, HTTPException, Request, status

from app.config import settings
from app.db import acquire_connection
from app.models import Role, UserStatus
from app.security import decode_access_token


def get_client_ip(request: Request) -> str:
    """Client IP as seen by the outermost trusted proxy.

    Only the rightmost `trusted_proxy_hops` X-Forwarded-For entries are
    written by infrastructure we control; anything left of them is
    client-supplied and could be forged into the audit log.
    """
    hops = settings.trusted_proxy_hops
    if hops > 0:
        entries = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if len(entries) >= hops:
            return entries[-hops]
    if request.client:
        return request.client.host
    return "unknown"


async def require_internal_api_key(x_internal_api_key: str | None = Header(default=None)) -> None:
    """Service-to-service auth for the detection worker; fails closed if unset."""
    expected = settings.internal_api_key
    if not expected or x_internal_api_key is None or not secrets.compare_digest(x_internal_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal API key")


async def get_db() -> AsyncIterator[asyncpg.Connection]:
    """One pooled connection per request, shared by every dependency that asks for it."""
    async with acquire_connection() as conn:
        yield conn


class CurrentUser:
    def __init__(self, user_id: str, role: Role) -> None:
        self.user_id = user_id
        self.role = role


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def resolve_session_user(conn: asyncpg.Connection, token: str | None) -> CurrentUser:
    """Validate an app session JWT and load the account it names.

    The role and status come from the users table on every call, never from
    the token: a disabled, deleted or re-roled account loses its old access
    on its next request instead of when the token expires.
    """
    if not token:
        raise _unauthorized("Not authenticated")
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired session") from exc

    try:
        row = await conn.fetchrow(
            "SELECT id, role, status, deleted_at FROM users WHERE id = $1::uuid", str(payload["sub"])
        )
    except (asyncpg.DataError, ValueError) as exc:
        raise _unauthorized("Invalid session") from exc
    if row is None or row["deleted_at"] is not None or row["status"] != UserStatus.ACTIVE.value:
        raise _unauthorized("This account is no longer active")
    return CurrentUser(user_id=str(row["id"]), role=Role(row["role"]))


async def get_current_user(request: Request, conn: asyncpg.Connection = Depends(get_db)) -> CurrentUser:
    return await resolve_session_user(conn, request.cookies.get(settings.session_cookie_name))


def require_role(*allowed_roles: Role):
    async def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return current_user

    return _dependency


require_admin = require_role(Role.ADMIN)
require_any_role = require_role(*Role)


async def get_rls_db(
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
) -> AsyncIterator[asyncpg.Connection]:
    """The request's connection inside a transaction with the RLS GUCs set.

    app.current_user_id / app.current_role are set transaction-locally (the
    `true` argument), so they cannot leak to the next request that reuses the
    pooled connection. The role is the one just read from the database.
    """
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.current_user_id', $1, true)", current_user.user_id)
        await conn.execute("SELECT set_config('app.current_role', $1, true)", current_user.role.value)
        yield conn
