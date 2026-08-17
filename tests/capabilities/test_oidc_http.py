"""OIDC HTTP endpoint integration tests.

Contract source: context/spec/capabilities/oidc-provider.md §3/§13.

Exercises the real router: discovery, jwks, browser authorize/login flow,
token endpoint, userinfo, revoke, logout — including HTTP-level negative
cases.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

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

ISSUER = "http://127.0.0.1:8000"
REDIRECT_URI = "http://127.0.0.1:3000/cb"
LOGOUT_REDIRECT = "http://127.0.0.1:3000/logged-out"
SCOPES = "openid profile email offline_access"
CONFIDENTIAL_REDIRECT_URI = "http://127.0.0.1:4321/auth/callback"
CONFIDENTIAL_CLIENT_SECRET = "site-confidential-secret-with-at-least-32-bytes"


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
    await RegisterClient(client_ctx)(
        name="User site BFF",
        client_type="confidential",
        redirect_uris=[CONFIDENTIAL_REDIRECT_URI],
        allowed_scopes=["openid", "profile", "email", "offline_access"],
        client_id="aiya-site",
        initial_secret=CONFIDENTIAL_CLIENT_SECRET,
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


async def test_confidential_client_uses_http_basic_at_protocol_boundary(
    client: httpx.AsyncClient,
) -> None:
    verifier, challenge = _pkce()
    login = await client.post(
        "/oidc/login",
        data={
            "username": "alice",
            "password": "pw-alice",
            "client_id": "aiya-site",
            "redirect_uri": CONFIDENTIAL_REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": "site-state",
            "nonce": "site-nonce",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert login.status_code == 302
    authorized = await client.get(login.headers["location"])
    assert authorized.status_code == 302
    code = parse_qs(urlsplit(authorized.headers["location"]).query)["code"][0]
    credentials = base64.b64encode(f"aiya-site:{CONFIDENTIAL_CLIENT_SECRET}".encode()).decode()

    exchanged = await client.post(
        "/oidc/token",
        headers={"Authorization": f"Basic {credentials}"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CONFIDENTIAL_REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["access_token"]


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


async def test_json_login_returns_frontend_callback_and_protocol_errors(
    client: httpx.AsyncClient,
) -> None:
    verifier, challenge = _pkce()
    params = _authorize_params(challenge=challenge)
    form = {
        "username": "alice",
        "password": "pw-alice",
        **params,
    }

    invalid = await client.post(
        "/oidc/login",
        data={**form, "redirect_uri": "http://127.0.0.1:3000/not-registered"},
        headers={"Accept": "application/json"},
    )
    assert invalid.status_code == 400
    assert invalid.json() == {
        "error": "invalid_request",
        "error_description": "redirect uri is not registered",
    }

    valid = await client.post(
        "/oidc/login",
        data=form,
        headers={"Accept": "application/json"},
    )
    assert valid.status_code == 200
    callback = valid.json()["redirect_uri"]
    assert callback.startswith(f"{REDIRECT_URI}?code=")
    assert valid.cookies.get("aiya_oidc_session") is not None
    assert valid.headers["cache-control"] == "no-store"
    assert valid.headers["pragma"] == "no-cache"

    callback_query = parse_qs(urlsplit(callback).query)
    token = await client.post(
        "/oidc/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "spa",
            "code": callback_query["code"][0],
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200


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


async def test_login_form_honors_supported_ui_locale(client: httpx.AsyncClient) -> None:
    params = _authorize_params()
    params["ui_locales"] = "zh-CN"
    chinese = await client.get("/oidc/authorize", params=params)
    assert 'lang="zh-CN"' in chinese.text
    assert "用户名" in chinese.text
    assert "登录" in chinese.text

    params["ui_locales"] = "en"
    english = await client.get("/oidc/authorize", params=params)
    assert 'lang="en"' in english.text
    assert "Username" in english.text
    assert "Sign in" in english.text


async def test_login_failure_lockout_returns_429_after_five_attempts(
    client: httpx.AsyncClient,
) -> None:
    params = _authorize_params()
    for _ in range(5):
        response = await client.post(
            "/oidc/login",
            data={"username": "alice", "password": "wrong", **params},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 401

    limited = await client.post(
        "/oidc/login",
        data={"username": "alice", "password": "wrong", **params},
        headers={"Accept": "application/json"},
    )
    assert limited.status_code == 429
    assert limited.json()["error"] == "temporarily_unavailable"


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


async def test_login_redirect_preserves_authorize_params(client: httpx.AsyncClient) -> None:
    verifier, challenge = _pkce()
    login = await client.post(
        "/oidc/login",
        data={
            "username": "alice",
            "password": "pw-alice",
            "client_id": "spa",
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": "st-redirect",
            "nonce": "n-redirect",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert login.status_code == 302
    location = login.headers["location"]
    assert location.startswith("/oidc/authorize?")
    # The authorize parameters must survive so the follow-up GET can issue a code.
    for param in ("client_id", "redirect_uri", "response_type", "scope", "state", "nonce"):
        assert f"{param}=" in location
    assert "state=st-redirect" in location
    assert "code_challenge=" in location
    # Credentials must never leak into the redirect.
    assert "username" not in location
    assert "password" not in location


async def test_failed_login_never_echoes_password(client: httpx.AsyncClient) -> None:
    response = await client.get("/oidc/authorize", params=_authorize_params())
    assert response.status_code == 200

    login = await client.post(
        "/oidc/login",
        data={
            "username": "alice",
            "password": "supersecret",
            "client_id": "spa",
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": "st-1",
            "nonce": "n-1",
        },
    )
    assert login.status_code == 401
    assert "supersecret" not in login.text
    # The form must still carry the authorize params for retry.
    assert "client_id" in login.text
    assert 'name="state" value="st-1"' in login.text


async def test_authorize_param_names_are_html_escaped(client: httpx.AsyncClient) -> None:
    # A crafted query-key breaks out of the hidden input's name attribute.
    malicious_key = 'x" autofocus onfocus="alert(1)'
    response = await client.get("/oidc/authorize", params={malicious_key: "v", "client_id": "spa"})
    assert response.status_code == 200
    # The quote is escaped so the key cannot break out of the name attribute.
    assert 'name="x&quot; autofocus onfocus=&quot;alert(1)"' in response.text
    assert 'name="x" autofocus' not in response.text


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
