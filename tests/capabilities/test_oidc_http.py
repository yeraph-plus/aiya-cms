"""OIDC HTTP endpoint integration tests.

Contract source: context/spec/capabilities/oidc-provider.md §3/§13.

Exercises the real router: discovery, jwks, browser authorize/login flow,
token endpoint, userinfo, revoke, logout — including HTTP-level negative
cases.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.oidc_provider.api import OidcHttpServices, build_router
from inc.capabilities.oidc_provider.clients import ClientCommandContext, RegisterClient
from inc.capabilities.oidc_provider.keys import InMemorySigningKeyStore, KeyService
from inc.capabilities.oidc_provider.services import (
    AuthorizationService,
    LogoutService,
    RevocationService,
    ServiceContext,
    TokenService,
    UserInfoService,
)
from inc.kernel.db import UoWFactory
from inc.kernel.events import EventSchemaRegistry, OutboxWriter
from inc.kernel.time.fake import FakeClock

ISSUER = "http://localhost:8000"
REDIRECT_URI = "http://localhost:3000/cb"
LOGOUT_REDIRECT = "http://localhost:3000/logged-out"
SCOPES = "openid profile email offline_access"


class FakeAuthenticator:
    async def authenticate(self, username: str, password: str) -> str | None:
        if username == "alice" and password == "pw-alice":
            return "u-1"
        return None


class FakeClaimsReader:
    async def claims_for(self, subject_id: str, scopes: set[str]) -> dict[str, Any]:
        claims: dict[str, Any] = {"sub": subject_id, "name": "Alice"}
        if "email" in scopes:
            claims["email"] = "alice@example.com"
        return claims


class FakeDecision:
    async def can_grant(self, subject_id: str, client_id: str, scopes: set[str]) -> bool:
        return True


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime.now(UTC))


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
async def client(
    uow_factory: UoWFactory,
    clock: FakeClock,
    schema_registry: EventSchemaRegistry,
) -> httpx.AsyncClient:
    keys = KeyService(uow_factory=uow_factory, store=InMemorySigningKeyStore(), clock=clock)
    ctx = ServiceContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        keys=keys,
        authenticator=FakeAuthenticator(),
        claims_reader=FakeClaimsReader(),
        authorization_reader=FakeDecision(),
        issuer=ISSUER,
    )
    client_ctx = ClientCommandContext(
        uow_factory=uow_factory, clock=clock, outbox=OutboxWriter(schema_registry, clock)
    )
    await RegisterClient(client_ctx)(
        name="Admin SPA",
        client_type="public",
        redirect_uris=[REDIRECT_URI],
        post_logout_redirect_uris=[LOGOUT_REDIRECT],
        allowed_scopes=["openid", "profile", "email", "offline_access"],
        client_id="spa",
    )
    services = OidcHttpServices(
        issuer=ISSUER,
        uow_factory=uow_factory,
        clock=clock,
        keys=keys,
        authenticator=FakeAuthenticator(),
        authorization=AuthorizationService(ctx),
        token=TokenService(ctx),
        userinfo=UserInfoService(ctx),
        revocation=RevocationService(ctx),
        logout=LogoutService(ctx),
        secure_cookies=False,
    )
    await keys.ensure_active_key()  # boot establishes the active signing key
    app = FastAPI()
    app.include_router(build_router(services))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=ISSUER) as http_client:
        yield http_client


def _pkce() -> tuple[str, str]:
    import base64
    import hashlib
    import secrets

    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def _authorize_params(
    *, redirect: str = REDIRECT_URI, challenge: str | None = None
) -> dict[str, str]:
    params: dict[str, str] = {
        "client_id": "spa",
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPES,
        "state": "st-1",
        "nonce": "n-1",
    }
    if challenge is not None:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    return params


async def test_discovery_and_jwks(client: httpx.AsyncClient) -> None:
    response = await client.get("/.well-known/openid-configuration")
    assert response.status_code == 200
    body = response.json()
    assert body["issuer"] == ISSUER
    assert body["authorization_endpoint"] == f"{ISSUER}/oidc/authorize"

    jwks = await client.get("/oidc/jwks")
    assert jwks.status_code == 200
    assert jwks.json()["keys"]


async def test_full_browser_flow(client: httpx.AsyncClient) -> None:
    verifier, challenge = _pkce()

    # First visit: login form, no redirect leak.
    response = await client.get("/oidc/authorize", params=_authorize_params(challenge=challenge))
    assert response.status_code == 200
    assert "form" in response.text

    # Bad credentials -> 401 form again.
    login = await client.post(
        "/oidc/login",
        data={
            "username": "alice",
            "password": "wrong",
            **{
                k: v
                for k, v in _authorize_params(challenge=challenge).items()
                if k
                in (
                    "client_id",
                    "redirect_uri",
                    "response_type",
                    "scope",
                    "state",
                    "nonce",
                    "code_challenge",
                    "code_challenge_method",
                )
            },
        },
    )
    assert login.status_code == 401

    # Good credentials -> session cookie + redirect to authorize.
    login = await client.post(
        "/oidc/login",
        data={
            "username": "alice",
            "password": "pw-alice",
            "client_id": "spa",
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": "st-1",
            "nonce": "n-1",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert login.status_code == 302
    cookie = login.cookies.get("aiya_oidc_session")
    assert cookie is not None

    # Authorize with session cookie -> code redirect.
    response = await client.get("/oidc/authorize", params=_authorize_params(challenge=challenge))
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{REDIRECT_URI}?code=")
    assert "state=st-1" in location
    code = location.split("code=")[1].split("&")[0]

    # Token exchange with PKCE.
    token_response = await client.post(
        "/oidc/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "spa",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    assert token_response.status_code == 200
    body = token_response.json()
    assert "no-store" in token_response.headers["cache-control"]
    assert body["token_type"] == "Bearer"
    assert body["id_token"]
    assert body["refresh_token"]

    # Userinfo with the access token.
    userinfo = await client.get(
        "/oidc/userinfo", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert userinfo.status_code == 200
    assert userinfo.json()["sub"] == "u-1"
    assert userinfo.json()["email"] == "alice@example.com"

    # Refresh rotation via HTTP.
    refreshed = await client.post(
        "/oidc/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "spa",
            "refresh_token": body["refresh_token"],
        },
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != body["refresh_token"]

    # Reuse of the rotated token -> invalid_grant.
    reused = await client.post(
        "/oidc/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "spa",
            "refresh_token": body["refresh_token"],
        },
    )
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"

    # Logout with exact post-logout redirect.
    logout = await client.get(
        "/oidc/logout",
        params={
            "id_token_hint": body["id_token"],
            "post_logout_redirect_uri": LOGOUT_REDIRECT,
        },
    )
    assert logout.status_code == 302
    assert logout.headers["location"] == LOGOUT_REDIRECT


async def test_http_pkce_downgrade_and_redirect_attacks(
    client: httpx.AsyncClient,
) -> None:
    verifier, challenge = _pkce()

    # Establish a session first.
    login = await client.post(
        "/oidc/login",
        data={
            "username": "alice",
            "password": "pw-alice",
            "client_id": "spa",
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": "st-1",
            "nonce": "n-1",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert login.status_code == 302

    # Authorize without a PKCE challenge -> invalid_request.
    response = await client.get("/oidc/authorize", params=_authorize_params())
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"

    # Unregistered redirect uri -> invalid_request (no open redirect).
    response = await client.get(
        "/oidc/authorize",
        params=_authorize_params(redirect="http://evil.example.com/cb", challenge=challenge),
    )
    assert response.status_code == 400
    assert "evil" not in response.headers.get("location", "")

    # Valid request -> code bound to the registered redirect.
    response = await client.get("/oidc/authorize", params=_authorize_params(challenge=challenge))
    assert response.status_code == 302
    code = response.headers["location"].split("code=")[1].split("&")[0]

    wrong_verifier = await client.post(
        "/oidc/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "spa",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": "x" * 64,
        },
    )
    assert wrong_verifier.status_code == 400
    assert wrong_verifier.json()["error"] == "invalid_grant"

    # Missing verifier also fails.
    no_verifier = await client.post(
        "/oidc/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "spa",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
    )
    assert no_verifier.status_code == 400
    assert no_verifier.json()["error"] == "invalid_grant"


async def test_revocation_endpoint_is_idempotent(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/oidc/revoke",
        data={"client_id": "spa", "token": "unknown-token", "token_type_hint": "refresh_token"},
    )
    assert response.status_code == 200


async def test_unsupported_grant_type(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/oidc/token",
        data={"grant_type": "password", "client_id": "spa", "username": "a", "password": "b"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"
