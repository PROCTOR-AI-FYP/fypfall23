"""FastAPI dependencies: client IP, plain DB connections, RLS-scoped DB
connections, and JWT-authenticated current-user / role-gating dependencies.
"""
from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

import asyncpg
import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.db import acquire_connection, acquire_rls_connection
from app.models import Role
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_client_ip(request: Request) -> str:
    """Client IP as seen by the outermost trusted proxy.

    Only the rightmost `trusted_proxy_hops` X-Forwarded-For entries are
    written by infrastructure we control; anything left of them is
    client-supplied and would let an attacker rotate fake IPs past the
    per-IP signup rate limit.
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


async def get_db(request: Request) -> AsyncIterator[asyncpg.Connection]:
    async with acquire_connection() as conn:
        yield conn


class CurrentUser:
    def __init__(self, user_id: str, role: Role) -> None:
        self.user_id = user_id
        self.role = role


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    try:
        role = Role(payload["role"])
        user_id = payload["sub"]
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload") from exc

    return CurrentUser(user_id=user_id, role=role)


def require_role(*allowed_roles: Role):
    async def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return current_user

    return _dependency


require_admin = require_role(Role.ADMIN)


async def get_rls_db(
    current_user: CurrentUser = Depends(get_current_user),
) -> AsyncIterator[asyncpg.Connection]:
    """DB connection with the RLS session GUCs set from the JWT of this request.

    See app/db.py::acquire_rls_connection for how app.current_user_id and
    app.current_role are populated and scoped to the transaction.
    """
    async with acquire_rls_connection(user_id=current_user.user_id, role=current_user.role.value) as conn:
        yield conn
