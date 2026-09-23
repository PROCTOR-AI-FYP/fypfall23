"""CSRF protection for the cookie-authenticated API.

The session is an httpOnly cookie, which the browser attaches to requests a
hostile page triggers too. Every state-changing /api request must therefore
carry the custom CSRF_HEADER. A cross-origin page cannot add a custom header
without a CORS preflight, and the preflight only succeeds for the exact
origins in CORS_ALLOWED_ORIGINS. As a second layer, a request whose Origin
header is present but not allowed is refused outright.

/internal/* is exempt: it is authenticated by X-Internal-Api-Key, not a cookie.
"""
from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

CSRF_HEADER = "x-proctorai-csrf"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PROTECTED_PREFIX = "/api/"


class CSRFMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS or not scope["path"].startswith(PROTECTED_PREFIX):
            await self.app(scope, receive, send)
            return

        headers = {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in scope["headers"]}
        origin = headers.get("origin")
        if origin is not None and origin.rstrip("/") not in self.allowed_origins:
            await _reject(send, "Request origin is not allowed.")
            return
        if not headers.get(CSRF_HEADER):
            await _reject(send, "Missing CSRF protection header.")
            return
        await self.app(scope, receive, send)


async def _reject(send: Send, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": 403,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})
