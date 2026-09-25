"""Verification of Supabase Auth access tokens from Google sign-in.

Signing mode: this project signs access tokens with an asymmetric key
published at <SUPABASE_URL>/auth/v1/.well-known/jwks.json (confirmed on
2026-09-24: one EC P-256 key, alg ES256). Only asymmetric algorithms are
accepted, so a token signed with a guessed or leaked shared secret (HS256),
or an unsigned one (alg "none"), can never verify. There is deliberately no
legacy HS256 fallback: the project does not use that mode.

What a token must satisfy, beyond a valid signature from a published key:
  - aud == "authenticated", iss == <SUPABASE_URL>/auth/v1, unexpired
  - sub and email present
  - the identity came from Google (app_metadata). Supabase can also mint
    tokens for email/password or magic-link users; those prove nothing about
    ownership of a university mailbox if email confirmation were ever turned
    off, so they are refused outright.
The university-domain check on the email happens in the caller, server-side,
regardless of the `hd` hint the frontend sends to Google.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError

from app.config import settings

ALLOWED_ALGORITHMS = ["ES256", "RS256", "EdDSA"]
REQUIRED_CLAIMS = ["exp", "iat", "sub", "email", "aud", "iss"]
GOOGLE_PROVIDER = "google"
JWKS_FETCH_TIMEOUT_SECONDS = 5


class SupabaseTokenError(Exception):
    """The token is malformed, unsigned, badly signed, expired, or not from Google."""


class SupabaseAuthUnavailable(Exception):
    """The JWKS endpoint could not be reached, so no token can be verified right now."""


@dataclass(frozen=True)
class SupabaseIdentity:
    sub: str
    email: str
    full_name: str | None


_jwk_client: PyJWKClient | None = None


def get_jwk_client() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(
            settings.supabase_jwks_url,
            cache_keys=True,
            lifespan=settings.supabase_jwks_cache_seconds,
            timeout=JWKS_FETCH_TIMEOUT_SECONDS,
        )
    return _jwk_client


def _came_from_google(claims: dict[str, Any]) -> bool:
    app_metadata = claims.get("app_metadata")
    if not isinstance(app_metadata, dict):
        return False
    providers = app_metadata.get("providers")
    return app_metadata.get("provider") == GOOGLE_PROVIDER or (
        isinstance(providers, list) and GOOGLE_PROVIDER in providers
    )


def _full_name(claims: dict[str, Any]) -> str | None:
    metadata = claims.get("user_metadata")
    if not isinstance(metadata, dict):
        return None
    for key in ("full_name", "name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return None


def _verify_sync(token: str) -> dict[str, Any]:
    # Resolves the key by the token's `kid` from the published JWKS (cached),
    # then verifies the signature with it. Both steps raise on any mismatch.
    signing_key = get_jwk_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=ALLOWED_ALGORITHMS,
        audience=settings.supabase_jwt_audience,
        issuer=settings.supabase_issuer,
        options={"require": REQUIRED_CLAIMS, "verify_signature": True},
        leeway=60,
    )


async def verify_supabase_token(token: str) -> SupabaseIdentity:
    try:
        # PyJWKClient fetches over blocking urllib on a cache miss.
        claims = await asyncio.to_thread(_verify_sync, token)
    except PyJWKClientConnectionError as exc:
        raise SupabaseAuthUnavailable("Could not reach the Supabase JWKS endpoint.") from exc
    except jwt.PyJWTError as exc:
        raise SupabaseTokenError(type(exc).__name__) from exc

    sub, email = claims.get("sub"), claims.get("email")
    if not isinstance(sub, str) or not sub or not isinstance(email, str) or "@" not in email:
        raise SupabaseTokenError("missing_identity_claims")
    if not _came_from_google(claims):
        raise SupabaseTokenError("not_google_identity")
    return SupabaseIdentity(sub=sub, email=email, full_name=_full_name(claims))
