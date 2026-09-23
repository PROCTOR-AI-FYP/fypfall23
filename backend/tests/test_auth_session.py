"""Google sign-in exchange: POST /api/auth/session, /me, /logout, CSRF.

Tokens are signed with a locally generated EC P-256 key, published through a
PyJWKClient whose HTTP fetch is replaced by the test's JWKS document; kid
lookup, algorithm allowlist, signature, audience, issuer and expiry checks
all run through the real verification code.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import AsyncClient
from jwt import PyJWKClient
from jwt.algorithms import ECAlgorithm
from jwt.exceptions import PyJWKClientConnectionError

from app import supabase_auth
from app.config import settings
from app.csrf import CSRF_HEADER
from tests.helpers import CSRF_HEADERS, STUDENT_A_EMAIL, TEACHER_EMAIL

SUPABASE_URL = "https://testproject.supabase.co"
KID = "test-key-1"


class _LocalJWKClient(PyJWKClient):
    """PyJWKClient with the network fetch replaced; everything else is the real class."""

    def __init__(self, jwks: dict[str, Any] | None) -> None:
        super().__init__(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", cache_keys=False)
        self._jwks = jwks

    def fetch_data(self) -> Any:
        if self._jwks is None:
            raise PyJWKClientConnectionError("unreachable")
        return self._jwks


def _jwks_for(private_key: ec.EllipticCurvePrivateKey, kid: str = KID) -> dict[str, Any]:
    jwk = ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": kid, "alg": "ES256", "use": "sig"}]}


@pytest.fixture
def signing_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[ec.EllipticCurvePrivateKey]:
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(supabase_auth, "_jwk_client", _LocalJWKClient(_jwks_for(key)))
    yield key


def make_token(
    key: ec.EllipticCurvePrivateKey,
    *,
    email: str,
    sub: str | None = None,
    provider: str = "google",
    kid: str = KID,
    **overrides: Any,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub or str(uuid.uuid4()),
        "email": email,
        "aud": "authenticated",
        "iss": f"{SUPABASE_URL}/auth/v1",
        "iat": now,
        "exp": now + 3600,
        "role": "authenticated",
        "app_metadata": {"provider": provider, "providers": [provider]},
        "user_metadata": {"full_name": "Test Person", "email_verified": True},
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})


async def _exchange(client: AsyncClient, token: str):  # noqa: ANN202
    return await client.post("/api/auth/session", json={"supabase_access_token": token})


async def _audit(admin_conn: asyncpg.Connection, action: str) -> list[asyncpg.Record]:
    return await admin_conn.fetch("SELECT actor_id, target, new_value FROM audit_log WHERE action = $1", action)


# --- Account rules ---------------------------------------------------------


async def test_unknown_student_email_is_auto_provisioned(
    client: AsyncClient, admin_conn: asyncpg.Connection, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    sub = str(uuid.uuid4())
    response = await _exchange(client, make_token(signing_key, email="245001@students.au.edu.pk", sub=sub))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "student" and body["registration_or_employee_no"] == "245001"
    assert body["full_name"] == "Test Person" and body["activated"] is True
    assert "access_token" not in body and "supabase_user_id" not in body

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{settings.session_cookie_name}=")
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie

    row = await admin_conn.fetchrow("SELECT role, supabase_user_id, auth_provider FROM users WHERE email = '245001@students.au.edu.pk'")
    assert (row["role"], str(row["supabase_user_id"]), row["auth_provider"]) == ("student", sub, "google")
    assert [r["new_value"] for r in await _audit(admin_conn, "sign_in")] == ['{"outcome": "student_provisioned"}']

    me = await client.get("/api/auth/me")  # the client's cookie jar now holds the session
    assert me.status_code == 200 and me.json()["email"] == "245001@students.au.edu.pk"


async def test_unknown_staff_email_is_refused(
    client: AsyncClient, admin_conn: asyncpg.Connection, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    response = await _exchange(client, make_token(signing_key, email="new.lecturer@students.au.edu.pk"))
    assert response.status_code == 403
    assert "administrator" in response.json()["detail"]
    assert "set-cookie" not in response.headers
    assert await admin_conn.fetchval("SELECT count(*) FROM users WHERE email = 'new.lecturer@students.au.edu.pk'") == 0
    assert '"staff_not_provisioned"' in (await _audit(admin_conn, "sign_in"))[0]["new_value"]


async def test_staff_account_activates_on_first_sign_in_then_signs_in(
    client: AsyncClient, admin_conn: asyncpg.Connection, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    sub = str(uuid.uuid4())
    # Google returns whatever casing the account has; matching is case-insensitive.
    first = await _exchange(client, make_token(signing_key, email="M.Bilal@Students.AU.edu.pk", sub=sub))
    assert first.status_code == 200, first.text
    assert first.json()["role"] == "teacher" and first.json()["activated"] is True
    assert str(await admin_conn.fetchval("SELECT supabase_user_id FROM users WHERE email = $1", TEACHER_EMAIL)) == sub

    again = await _exchange(client, make_token(signing_key, email=TEACHER_EMAIL, sub=sub))
    assert again.status_code == 200
    outcomes = sorted(r["new_value"] for r in await _audit(admin_conn, "sign_in"))
    assert outcomes == ['{"outcome": "account_activated"}', '{"outcome": "signed_in"}']


async def test_relink_to_a_different_identity_is_rejected_and_audited(
    client: AsyncClient, admin_conn: asyncpg.Connection, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    original = str(await admin_conn.fetchval("SELECT supabase_user_id FROM users WHERE email = $1", STUDENT_A_EMAIL))
    intruder = str(uuid.uuid4())

    response = await _exchange(client, make_token(signing_key, email=STUDENT_A_EMAIL, sub=intruder))
    assert response.status_code == 403
    assert "different Google identity" in response.json()["detail"]
    assert "set-cookie" not in response.headers
    # Never silently re-linked.
    assert str(await admin_conn.fetchval("SELECT supabase_user_id FROM users WHERE email = $1", STUDENT_A_EMAIL)) == original

    events = await _audit(admin_conn, "security_relink_rejected")
    assert len(events) == 1
    assert events[0]["target"] == STUDENT_A_EMAIL
    assert '"relink_rejected"' in events[0]["new_value"] and intruder in events[0]["new_value"]
    assert await _audit(admin_conn, "sign_in") == []


async def test_identity_already_linked_elsewhere_cannot_activate_or_provision(
    client: AsyncClient, admin_conn: asyncpg.Connection, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    taken = str(await admin_conn.fetchval("SELECT supabase_user_id FROM users WHERE email = $1", STUDENT_A_EMAIL))
    activation = await _exchange(client, make_token(signing_key, email=TEACHER_EMAIL, sub=taken))
    provision = await _exchange(client, make_token(signing_key, email="245002@students.au.edu.pk", sub=taken))
    assert activation.status_code == provision.status_code == 403
    assert await admin_conn.fetchval("SELECT supabase_user_id FROM users WHERE email = $1", TEACHER_EMAIL) is None
    assert await admin_conn.fetchval("SELECT count(*) FROM users WHERE email = '245002@students.au.edu.pk'") == 0
    assert len(await _audit(admin_conn, "security_relink_rejected")) == 2


async def test_other_domains_and_disabled_accounts_are_refused(
    client: AsyncClient, admin_conn: asyncpg.Connection, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    # The `hd` hint is client-side only; this is the real check.
    for email in ("245003@gmail.com", "245003@students.au.edu.pk.evil.com", "m.bilal@au.edu.pk"):
        response = await _exchange(client, make_token(signing_key, email=email))
        assert response.status_code == 403, email
    await admin_conn.execute("UPDATE users SET status = 'disabled' WHERE email = $1", TEACHER_EMAIL)
    assert (await _exchange(client, make_token(signing_key, email=TEACHER_EMAIL))).status_code == 403
    await admin_conn.execute("UPDATE users SET status = 'active', deleted_at = now() WHERE email = $1", TEACHER_EMAIL)
    assert (await _exchange(client, make_token(signing_key, email=TEACHER_EMAIL))).status_code == 403


# --- Token verification ----------------------------------------------------


def _unsigned(email: str) -> str:
    return jwt.encode(
        {"sub": str(uuid.uuid4()), "email": email, "aud": "authenticated", "iss": f"{SUPABASE_URL}/auth/v1",
         "iat": int(time.time()), "exp": int(time.time()) + 3600, "app_metadata": {"provider": "google"}},
        key=None, algorithm="none", headers={"kid": KID},
    )


def _hs256(email: str) -> str:
    """Signed with a shared secret: must never verify, even with the right kid."""
    return jwt.encode(
        {"sub": str(uuid.uuid4()), "email": email, "aud": "authenticated", "iss": f"{SUPABASE_URL}/auth/v1",
         "iat": int(time.time()), "exp": int(time.time()) + 3600, "app_metadata": {"provider": "google"}},
        "super-secret-jwt-token-with-at-least-32-characters-long", algorithm="HS256", headers={"kid": KID},
    )


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda key: "not-a-jwt", id="malformed"),
        pytest.param(lambda key: "a.b.c", id="garbage-segments"),
        pytest.param(lambda key: _unsigned("245010@students.au.edu.pk"), id="alg-none-unsigned"),
        pytest.param(lambda key: _hs256("245010@students.au.edu.pk"), id="hs256-shared-secret"),
        pytest.param(lambda key: make_token(ec.generate_private_key(ec.SECP256R1()), email="245010@students.au.edu.pk"),
                     id="signed-by-unpublished-key"),
        pytest.param(lambda key: make_token(key, email="245010@students.au.edu.pk", kid="rotated-away"), id="unknown-kid"),
        pytest.param(lambda key: make_token(key, email="245010@students.au.edu.pk", exp=int(time.time()) - 60,
                                            iat=int(time.time()) - 3700), id="expired"),
        pytest.param(lambda key: make_token(key, email="245010@students.au.edu.pk", aud="anon"), id="wrong-audience"),
        pytest.param(lambda key: make_token(key, email="245010@students.au.edu.pk",
                                            iss="https://evil.supabase.co/auth/v1"), id="wrong-issuer"),
        pytest.param(lambda key: make_token(key, email="245010@students.au.edu.pk", provider="email"),
                     id="not-a-google-identity"),
        pytest.param(lambda key: make_token(key, email="245010@students.au.edu.pk", sub="not-a-uuid"), id="non-uuid-sub"),
    ],
)
async def test_bad_tokens_are_rejected(
    client: AsyncClient, admin_conn: asyncpg.Connection, signing_key: ec.EllipticCurvePrivateKey, build: Any
) -> None:
    response = await _exchange(client, build(signing_key))
    assert response.status_code == 401, response.text
    assert "set-cookie" not in response.headers
    assert await admin_conn.fetchval("SELECT count(*) FROM users WHERE email = '245010@students.au.edu.pk'") == 0
    assert '"invalid_token"' in (await _audit(admin_conn, "sign_in"))[0]["new_value"]


async def test_tampered_payload_fails_signature_check(
    client: AsyncClient, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    header, _, signature = make_token(signing_key, email="245011@students.au.edu.pk").split(".")
    forged_payload = jwt.utils.base64url_encode(
        b'{"sub":"' + str(uuid.uuid4()).encode() + b'","email":"hod.cs@students.au.edu.pk","aud":"authenticated",'
        b'"iss":"' + SUPABASE_URL.encode() + b'/auth/v1","iat":1,"exp":9999999999,"app_metadata":{"provider":"google"}}'
    ).decode()
    assert (await _exchange(client, f"{header}.{forged_payload}.{signature}")).status_code == 401


async def test_unreachable_jwks_fails_closed_with_503(
    client: AsyncClient, signing_key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supabase_auth, "_jwk_client", _LocalJWKClient(None))
    response = await _exchange(client, make_token(signing_key, email="245012@students.au.edu.pk"))
    assert response.status_code == 503
    assert "set-cookie" not in response.headers


def test_only_asymmetric_algorithms_are_allowed() -> None:
    assert not {"HS256", "HS384", "HS512", "none"} & set(supabase_auth.ALLOWED_ALGORITHMS)


# --- Session cookie, /me, logout, CSRF --------------------------------------


async def test_me_requires_a_valid_cookie(client: AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401
    bad = {"Cookie": f"{settings.session_cookie_name}=forged.jwt.value"}
    assert (await client.get("/api/auth/me", headers=bad)).status_code == 401
    forged = jwt.encode({"sub": str(uuid.uuid4()), "role": "admin", "iat": int(time.time()), "exp": int(time.time()) + 60},
                        "wrong-secret-of-sufficient-length-for-hs256-0000", algorithm="HS256")
    assert (await client.get("/api/auth/me", headers={"Cookie": f"{settings.session_cookie_name}={forged}"})).status_code == 401


async def test_secure_cookie_flag_follows_configuration(
    client: AsyncClient, signing_key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "session_cookie_secure", True)
    monkeypatch.setattr(settings, "session_cookie_samesite", "none")
    response = await _exchange(client, make_token(signing_key, email="245013@students.au.edu.pk"))
    assert "Secure" in response.headers["set-cookie"] and "SameSite=none" in response.headers["set-cookie"]


async def test_logout_clears_the_cookie(
    client: AsyncClient, admin_conn: asyncpg.Connection, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    await _exchange(client, make_token(signing_key, email="245014@students.au.edu.pk"))
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post("/api/auth/logout")
    assert response.status_code == 204
    assert f'{settings.session_cookie_name}=""' in response.headers["set-cookie"] or "Max-Age=0" in response.headers["set-cookie"]
    assert (await client.get("/api/auth/me")).status_code == 401
    assert len(await _audit(admin_conn, "sign_out")) == 1
    # Signing out with no session still succeeds.
    assert (await client.post("/api/auth/logout")).status_code == 204


async def test_state_changing_requests_need_the_csrf_header(
    client: AsyncClient, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    token = make_token(signing_key, email="245015@students.au.edu.pk")
    no_header = await client.post(
        "/api/auth/session", json={"supabase_access_token": token}, headers={CSRF_HEADER: ""}
    )
    assert no_header.status_code == 403 and "CSRF" in no_header.json()["detail"]

    # The test environment allows no browser origins at all, so any Origin is foreign.
    foreign_origin = await client.post(
        "/api/auth/session", json={"supabase_access_token": token},
        headers={"Origin": "https://evil.example", **CSRF_HEADERS},
    )
    assert foreign_origin.status_code == 403

    # Reads are unaffected; internal worker endpoints use their API key instead.
    assert (await client.get("/api/auth/me", headers={CSRF_HEADER: ""})).status_code == 401
    assert (await client.post("/internal/frames", json={}, headers={CSRF_HEADER: ""})).status_code == 401
