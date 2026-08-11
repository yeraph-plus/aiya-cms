"""OIDC Provider protocol tests.

Contract source: context/spec/capabilities/oidc-provider.md §13.

Covers the exit-gate negative tests: redirect exact match, PKCE downgrade,
code replay, client binding, nonce, issuer/audience, algorithm confusion,
refresh rotation/reuse, logout, revocation and key rotation.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any

import jwt as pyjwt
import pytest
from sqlalchemy import select

from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
from inc.capabilities.oidc_provider.clients import (
    ClientCommandContext,
    RegisterClient,
    UpdateClient,
)
from inc.capabilities.oidc_provider.handlers import OidcDiagnostics
from inc.capabilities.oidc_provider.keys import (
    InMemorySigningKeyStore,
    KeyService,
    load_public_key,
    verify_jwt,
)
from inc.capabilities.oidc_provider.models import (
    OidcGrantConsent,
    OidcRefreshFamily,
    OidcSession,
    StringList,
)
from inc.capabilities.oidc_provider.schemas import ClientRegistrationResult, OidcError
from inc.capabilities.oidc_provider.services import (
    AuthorizationService,
    GrantConsentService,
    LogoutService,
    RevocationService,
    ServiceContext,
    TokenService,
    UserInfoService,
)
from inc.kernel.db import UoWFactory
from inc.kernel.events import EventSchemaRegistry, OutboxWriter

ISSUER = "http://127.0.0.1:8000"
REDIRECT_URI = "http://127.0.0.1:3000/cb"
SCOPES = "openid profile email offline_access"
CLIENT_SECRET = "confidential-secret-1"


@pytest.fixture
def clock() -> Any:
    """PyJWT validates iat/exp against real wall time, so the fake clock
    tracks the present (leeway covers sub-second drift)."""

    from datetime import UTC, datetime

    from inc.kernel.time.fake import FakeClock

    return FakeClock(datetime.now(UTC))


class FakeAuthenticator:
    async def authenticate(self, username: str, password: str) -> str | None:
        if username == "alice" and password == "pw-alice":
            return "u-1"
        if username == "bob" and password == "pw-bob":
            return "u-2"
        return None


class FakeClaimsReader:
    async def claims_for(self, subject_id: str, scopes: set[str]) -> dict[str, Any]:
        claims: dict[str, Any] = {"sub": subject_id}
        if "profile" in scopes:
            claims["name"] = "Alice A" if subject_id == "u-1" else "Bob B"
        if "email" in scopes:
            claims["email"] = "alice@example.com" if subject_id == "u-1" else "bob@example.com"
            claims["email_verified"] = True
        return claims


class FakeAuthorizationReader:
    def __init__(self, deny_subjects: set[str] | None = None) -> None:
        self._deny = deny_subjects or set()

    async def can_grant(self, subject_id: str, client_id: str, scopes: set[str]) -> bool:
        return subject_id not in self._deny


class FakeSecurityEvents:
    def __init__(self) -> None:
        self.revoked: list[tuple[str, str]] = []

    async def revoke_subject_sessions(self, subject_id: str, reason: str) -> None:
        self.revoked.append((subject_id, reason))


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def keys(uow_factory: UoWFactory, clock: Any) -> KeyService:
    return KeyService(uow_factory=uow_factory, store=InMemorySigningKeyStore(), clock=clock)


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    schema_registry: EventSchemaRegistry,
    keys: KeyService,
) -> ServiceContext:
    return ServiceContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        keys=keys,
        authenticator=FakeAuthenticator(),
        claims_reader=FakeClaimsReader(),
        authorization_reader=FakeAuthorizationReader(),
        issuer=ISSUER,
        audit_trace_id="trace-1",
    )


@pytest.fixture
def client_ctx(
    uow_factory: UoWFactory,
    clock: Any,
    schema_registry: EventSchemaRegistry,
) -> ClientCommandContext:
    return ClientCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        audit_actor_id="admin-1",
    )


async def register_clients(
    client_ctx: ClientCommandContext,
) -> tuple[ClientRegistrationResult, ClientRegistrationResult]:
    spa = await RegisterClient(client_ctx)(
        name="Admin SPA",
        client_type="public",
        redirect_uris=[REDIRECT_URI],
        post_logout_redirect_uris=["http://127.0.0.1:3000/logged-out"],
        allowed_scopes=["openid", "profile", "email", "offline_access"],
        allow_refresh=True,
        client_id="spa",
    )
    api = await RegisterClient(client_ctx)(
        name="Confidential API",
        client_type="confidential",
        redirect_uris=["http://127.0.0.1:4000/cb"],
        allowed_scopes=["openid", "profile", "email", "offline_access"],
        client_id="api",
    )
    return spa, api


def _pkce_pair() -> tuple[str, str]:
    import base64

    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


async def _authorize_and_exchange(
    ctx: ServiceContext,
    *,
    client_id: str = "spa",
    redirect_uri: str = REDIRECT_URI,
    scopes: str = SCOPES,
    nonce: str = "n-1",
    subject: str = "u-1",
    code_verifier: str | None = None,
    code_challenge: str | None = None,
    client_secret: str | None = None,
) -> dict[str, Any]:
    verifier, challenge = _pkce_pair()
    code = await AuthorizationService(ctx).issue_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        response_type="code",
        scope=scopes,
        state="st-1",
        nonce=nonce,
        code_challenge=challenge,
        code_challenge_method="S256",
        subject_id=subject,
        session_handle=None,
    )
    raw_code = code.split("code=")[1].split("&")[0]
    return await _exchange_code(
        ctx,
        client_id=client_id,
        code=raw_code,
        redirect_uri=redirect_uri,
        verifier=verifier,
        client_secret=client_secret,
    )


async def _exchange_code(
    ctx: ServiceContext,
    *,
    client_id: str,
    code: str,
    redirect_uri: str,
    verifier: str,
    client_secret: str | None = None,
) -> dict[str, Any]:
    result = await TokenService(ctx).exchange(
        client_id=client_id,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=verifier,
        client_secret=client_secret,
    )
    return result.model_dump(exclude_none=True)


def test_discovery_contract(ctx: ServiceContext) -> None:
    from inc.capabilities.oidc_provider.discovery import DiscoveryService

    config = DiscoveryService(issuer=ISSUER).configuration()
    assert config["issuer"] == ISSUER
    assert config["authorization_endpoint"].startswith(ISSUER)
    assert "code" in config["response_types_supported"]
    assert "S256" in config["code_challenge_methods_supported"]
    assert config["id_token_signing_alg_values_supported"] == ["RS256"]


async def test_full_code_flow_with_pkce_and_nonce(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    spa, _ = await register_clients(client_ctx)
    tokens = await _authorize_and_exchange(ctx)
    assert tokens["token_type"] == "Bearer"
    assert tokens["id_token"] is not None
    assert tokens["refresh_token"] is not None

    key = await ctx.keys.ensure_active_key()
    public_keys = {key.kid: load_public_key(_jwk_for_test(key))}
    id_claims = verify_jwt(
        tokens["id_token"], public_keys=public_keys, audience="spa", issuer=ISSUER
    )
    assert id_claims["sub"] == "u-1"
    assert id_claims["nonce"] == "n-1"
    assert id_claims["azp"] == "spa"
    assert id_claims["aud"] == "spa"
    assert "auth_time" in id_claims

    access_claims = verify_jwt(
        tokens["access_token"], public_keys=public_keys, audience=ISSUER, issuer=ISSUER
    )
    assert access_claims["scope"].split() == ["email", "offline_access", "openid", "profile"]


def _jwk_for_test(key: Any) -> dict[str, Any]:
    numbers = key.private_key.public_key().public_numbers()
    import base64

    def b64u(value: int) -> str:
        length = (value.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode("ascii")

    return {"n": b64u(numbers.n), "e": b64u(numbers.e)}


async def test_redirect_uri_must_be_registered_exactly(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    await register_clients(client_ctx)
    verifier, challenge = _pkce_pair()
    with pytest.raises(OidcError) as excinfo:
        await AuthorizationService(ctx).issue_code(
            client_id="spa",
            redirect_uri="http://127.0.0.1:3000/EVIL",
            response_type="code",
            scope=SCOPES,
            state="st",
            nonce="n",
            code_challenge=challenge,
            code_challenge_method="S256",
            subject_id="u-1",
            session_handle=None,
        )
    assert excinfo.value.code == "invalid_request"
    assert "redirect" in (excinfo.value.description or "")


async def test_register_client_rejects_malformed_redirect_uris(
    client_ctx: ClientCommandContext,
) -> None:
    """Redirect URIs must be exact https URLs (or http loopback), never
    hostless https, wildcards, fragments or loopback-lookalike hosts."""

    bad = [
        "https://",  # no host
        "https:///path",  # no netloc
        "http://localhost.evil.com/cb",  # not loopback
        "http://localhost@evil.com/cb",  # userinfo tricks
        "https://example.com/cb*",  # wildcard
        "https://example.com/cb#frag",  # fragment
    ]
    for uri in bad:
        with pytest.raises(OidcError) as excinfo:
            await RegisterClient(client_ctx)(
                name="Bad",
                client_type="public",
                redirect_uris=[uri],
            )
        assert excinfo.value.code == "invalid_request", f"accepted {uri!r}"

    good = [
        "https://example.com/cb",
        "http://localhost:3000/cb",
        "http://127.0.0.1:3000/cb",
    ]
    for index, uri in enumerate(good):
        result = await RegisterClient(client_ctx)(
            name="Good",
            client_type="public",
            redirect_uris=[uri],
            client_id=f"good-{index}",
        )
        assert uri in result.client.redirect_uris


async def test_update_client_replaces_registered_redirect_uris(
    client_ctx: ClientCommandContext,
) -> None:
    await RegisterClient(client_ctx)(
        name="Admin SPA",
        client_type="public",
        redirect_uris=["http://127.0.0.1:7000/callback"],
        post_logout_redirect_uris=["http://127.0.0.1:7000/logged-out"],
        client_id="admin",
    )

    result = await UpdateClient(client_ctx)(
        client_id="admin",
        redirect_uris=["http://127.0.0.1:5173/callback"],
        post_logout_redirect_uris=["http://127.0.0.1:5173/logged-out"],
        allowed_scopes=["openid", "profile", "email", "offline_access"],
        allowed_audiences=["aiya-admin"],
    )

    assert result.redirect_uris == ["http://127.0.0.1:5173/callback"]
    assert result.post_logout_redirect_uris == ["http://127.0.0.1:5173/logged-out"]


async def test_pkce_downgrade_attempts_are_rejected(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    """A code issued with a challenge cannot be redeemed with a different
    verifier, and a verifier without a challenge is rejected."""

    await register_clients(client_ctx)
    verifier, challenge = _pkce_pair()

    code = await AuthorizationService(ctx).issue_code(
        client_id="spa",
        redirect_uri=REDIRECT_URI,
        response_type="code",
        scope=SCOPES,
        state="st",
        nonce="n",
        code_challenge=challenge,
        code_challenge_method="S256",
        subject_id="u-1",
        session_handle=None,
    )
    raw_code = code.split("code=")[1].split("&")[0]

    wrong_verifier = "x" * 64
    with pytest.raises(OidcError) as excinfo:
        await _exchange_code(
            ctx, client_id="spa", code=raw_code, redirect_uri=REDIRECT_URI, verifier=wrong_verifier
        )
    assert excinfo.value.code == "invalid_grant"


async def test_missing_challenge_is_rejected_at_authorize(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    await register_clients(client_ctx)
    with pytest.raises(OidcError) as excinfo:
        await AuthorizationService(ctx).issue_code(
            client_id="spa",
            redirect_uri=REDIRECT_URI,
            response_type="code",
            scope=SCOPES,
            state="st",
            nonce="n",
            code_challenge=None,
            code_challenge_method=None,
            subject_id="u-1",
            session_handle=None,
        )
    assert excinfo.value.code == "invalid_request"
    assert "PKCE" in (excinfo.value.description or "")


async def test_code_replay_is_rejected(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
    uow_factory: UoWFactory,
) -> None:
    await register_clients(client_ctx)
    verifier, challenge = _pkce_pair()
    code = await AuthorizationService(ctx).issue_code(
        client_id="spa",
        redirect_uri=REDIRECT_URI,
        response_type="code",
        scope=SCOPES,
        state="st",
        nonce="n",
        code_challenge=challenge,
        code_challenge_method="S256",
        subject_id="u-1",
        session_handle=None,
    )
    raw_code = code.split("code=")[1].split("&")[0]
    first = await _exchange_code(
        ctx, client_id="spa", code=raw_code, redirect_uri=REDIRECT_URI, verifier=verifier
    )
    assert first["access_token"]

    with pytest.raises(OidcError) as excinfo:
        await _exchange_code(
            ctx, client_id="spa", code=raw_code, redirect_uri=REDIRECT_URI, verifier=verifier
        )
    assert excinfo.value.code == "invalid_grant"
    assert "already used" in (excinfo.value.description or "")


async def test_code_binding_to_client_and_redirect(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    spa, api = await register_clients(client_ctx)
    verifier, challenge = _pkce_pair()
    code = await AuthorizationService(ctx).issue_code(
        client_id="spa",
        redirect_uri=REDIRECT_URI,
        response_type="code",
        scope=SCOPES,
        state="st",
        nonce="n",
        code_challenge=challenge,
        code_challenge_method="S256",
        subject_id="u-1",
        session_handle=None,
    )
    raw_code = code.split("code=")[1].split("&")[0]

    with pytest.raises(OidcError) as excinfo:
        await _exchange_code(
            ctx,
            client_id="api",
            code=raw_code,
            redirect_uri=REDIRECT_URI,
            verifier=verifier,
            client_secret=api.client_secret,
        )
    assert excinfo.value.code == "invalid_grant"

    with pytest.raises(OidcError):
        await _exchange_code(
            ctx,
            client_id="spa",
            code=raw_code,
            redirect_uri="http://127.0.0.1:3000/other",
            verifier=verifier,
        )


async def test_refresh_rotation_and_reuse_detection(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
    uow_factory: UoWFactory,
) -> None:
    await register_clients(client_ctx)
    tokens = await _authorize_and_exchange(ctx)
    first_refresh = tokens["refresh_token"]

    rotated = await TokenService(ctx).refresh(client_id="spa", refresh_token=first_refresh)
    assert rotated.refresh_token is not None
    assert rotated.refresh_token != first_refresh

    # Reuse of the rotated token revokes the whole family.
    with pytest.raises(OidcError) as excinfo:
        await TokenService(ctx).refresh(client_id="spa", refresh_token=first_refresh)
    assert excinfo.value.code == "invalid_grant"
    assert "reuse" in (excinfo.value.description or "")

    # The family is now revoked: even the fresh token is dead.
    with pytest.raises(OidcError):
        await TokenService(ctx).refresh(client_id="spa", refresh_token=rotated.refresh_token)

    async with uow_factory() as uow:
        family = (await uow.session.execute(select(OidcRefreshFamily))).scalars().first()
        assert family is not None and family.revoked_at is not None


async def test_refresh_token_bound_to_client(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    spa, api = await register_clients(client_ctx)
    tokens = await _authorize_and_exchange(ctx)
    with pytest.raises(OidcError) as excinfo:
        await TokenService(ctx).refresh(
            client_id="api", refresh_token=tokens["refresh_token"], client_secret=api.client_secret
        )
    assert excinfo.value.code == "invalid_grant"


async def test_confidential_client_secret_authentication(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    spa, api = await register_clients(client_ctx)
    assert api.client_secret is not None
    verifier, challenge = _pkce_pair()
    code = await AuthorizationService(ctx).issue_code(
        client_id="api",
        redirect_uri="http://127.0.0.1:4000/cb",
        response_type="code",
        scope="openid profile",
        state="st",
        nonce="n",
        code_challenge=challenge,
        code_challenge_method="S256",
        subject_id="u-1",
        session_handle=None,
    )
    raw_code = code.split("code=")[1].split("&")[0]
    with pytest.raises(OidcError):
        await _exchange_code(
            ctx,
            client_id="api",
            code=raw_code,
            redirect_uri="http://127.0.0.1:4000/cb",
            verifier=verifier,
            client_secret="wrong-secret",
        )
    result = await _exchange_code(
        ctx,
        client_id="api",
        code=raw_code,
        redirect_uri="http://127.0.0.1:4000/cb",
        verifier=verifier,
        client_secret=api.client_secret,
    )
    assert result["access_token"]
    # Secret is stored as digest only.
    async with ctx.uow_factory() as uow:
        from inc.capabilities.oidc_provider.models import OidcClientSecret

        row = (await uow.session.execute(select(OidcClientSecret))).scalars().first()
        assert row is not None and row.secret_digest != api.client_secret


async def test_algorithm_confusion_is_rejected(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    await register_clients(client_ctx)
    key = await ctx.keys.ensure_active_key()
    public_keys = {key.kid: load_public_key(_jwk_for_test(key))}

    # alg=none
    none_token = pyjwt.encode({"iss": ISSUER, "sub": "u-1", "aud": "spa"}, key="", algorithm="none")
    with pytest.raises(OidcError) as excinfo:
        verify_jwt(none_token, public_keys=public_keys, audience="spa", issuer=ISSUER)
    assert excinfo.value.code == "invalid_token"

    # alg=HS256 (symmetric confusion: HMAC with a guessable secret)
    hs_token = pyjwt.encode(
        {"iss": ISSUER, "sub": "u-1", "aud": "spa"},
        key="guessable-hmac-secret",
        algorithm="HS256",
    )
    with pytest.raises(OidcError) as excinfo:
        verify_jwt(hs_token, public_keys=public_keys, audience="spa", issuer=ISSUER)
    assert excinfo.value.code == "invalid_token"

    # Wrong audience / issuer
    signed = pyjwt.encode(
        {"iss": "https://evil.example.com", "sub": "u-1", "aud": "spa"},
        key=key.private_key,
        algorithm="RS256",
    )
    with pytest.raises(OidcError):
        verify_jwt(signed, public_keys=public_keys, audience="spa", issuer=ISSUER)


async def test_userinfo_returns_only_authorized_claims(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    await register_clients(client_ctx)
    tokens = await _authorize_and_exchange(ctx, scopes="openid profile")
    userinfo = await UserInfoService(ctx).userinfo(tokens["access_token"])
    assert userinfo["sub"] == "u-1"
    assert "name" in userinfo
    assert "email" not in userinfo  # email scope not authorized


async def test_revocation_is_idempotent_for_unknown_tokens(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    await register_clients(client_ctx)
    # Unknown token: protocol success, no existence oracle.
    await RevocationService(ctx).revoke(
        client_id="spa", token="unknown-token-value", token_type_hint="refresh_token"
    )


async def test_grants_are_listed_for_subject_and_revoke_invalidates_client_state(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
    uow_factory: UoWFactory,
) -> None:
    await register_clients(client_ctx)
    tokens = await _authorize_and_exchange(ctx)

    grants = GrantConsentService(ctx)
    listed = await grants.list_for_subject("u-1")
    assert [grant.client_id for grant in listed] == ["spa"]
    assert listed[0].client_name == "Admin SPA"
    assert listed[0].scopes == sorted(set(SCOPES.split()))

    await grants.revoke(subject_id="u-1", client_id="spa")

    assert await grants.list_for_subject("u-1") == []
    async with uow_factory() as uow:
        consent = (await uow.session.execute(select(OidcGrantConsent))).scalars().one()
        assert consent.revoked_at is not None
        session = (await uow.session.execute(select(OidcSession))).scalars().one()
        assert session.revoked_at is not None
        family = (await uow.session.execute(select(OidcRefreshFamily))).scalars().one()
        assert family.revoked_at is not None

    with pytest.raises(OidcError) as excinfo:
        await TokenService(ctx).refresh(client_id="spa", refresh_token=tokens["refresh_token"])
    assert excinfo.value.code == "invalid_grant"


async def test_grants_are_scoped_to_subject_and_ignore_revoked_rows(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
    uow_factory: UoWFactory,
) -> None:
    await register_clients(client_ctx)
    async with uow_factory() as uow:
        uow.session.add_all(
            [
                OidcGrantConsent(
                    subject_id="u-1",
                    client_id="spa",
                    scopes=StringList(items=["openid"]),
                    audiences=StringList(items=[]),
                    granted_at=ctx.clock.utc_now(),
                ),
                OidcGrantConsent(
                    subject_id="u-1",
                    client_id="api",
                    scopes=StringList(items=["openid"]),
                    audiences=StringList(items=[]),
                    granted_at=ctx.clock.utc_now(),
                    revoked_at=ctx.clock.utc_now(),
                ),
                OidcGrantConsent(
                    subject_id="u-2",
                    client_id="spa",
                    scopes=StringList(items=["openid"]),
                    audiences=StringList(items=[]),
                    granted_at=ctx.clock.utc_now(),
                ),
            ]
        )
        await uow.commit()

    listed = await GrantConsentService(ctx).list_for_subject("u-1")
    assert [(grant.client_id, grant.client_name) for grant in listed] == [("spa", "Admin SPA")]


async def test_logout_requires_hint_for_redirect_and_exact_match(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    spa, _ = await register_clients(client_ctx)
    tokens = await _authorize_and_exchange(ctx)

    with pytest.raises(OidcError) as excinfo:
        await LogoutService(ctx).logout(
            id_token_hint=None,
            post_logout_redirect_uri="http://127.0.0.1:3000/logged-out",
            session_cookie=None,
        )
    assert excinfo.value.code == "invalid_request"

    with pytest.raises(OidcError):
        await LogoutService(ctx).logout(
            id_token_hint=tokens["id_token"],
            post_logout_redirect_uri="http://127.0.0.1:3000/EVIL",
            session_cookie=None,
        )

    redirect = await LogoutService(ctx).logout(
        id_token_hint=tokens["id_token"],
        post_logout_redirect_uri="http://127.0.0.1:3000/logged-out",
        session_cookie=None,
    )
    assert redirect == "http://127.0.0.1:3000/logged-out"


async def test_security_event_revokes_sessions(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
    uow_factory: UoWFactory,
) -> None:
    await register_clients(client_ctx)
    await _authorize_and_exchange(ctx)

    subscriber = FakeSecurityEvents()

    envelope = _security_envelope(ctx, "identity.user_banned.v1", "u-1")
    async with uow_factory() as uow:
        from inc.kernel.events import InboxGuard

        await InboxGuard.process(
            uow,
            handler_key="oidc.revoke_on_security_event.v1",
            event_id=envelope.event_id,
            work=lambda: subscriber.revoke_subject_sessions("u-1", "identity.user_banned.v1"),
            processed_at=ctx.clock.utc_now(),
        )
        await uow.commit()
    assert subscriber.revoked == [("u-1", "identity.user_banned.v1")]


async def test_security_event_revokes_refresh_grants(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    """Ban/password-change must stop refresh rotation, not just cookies."""

    await register_clients(client_ctx)
    tokens = await _authorize_and_exchange(ctx)
    assert tokens["refresh_token"] is not None

    from inc.capabilities.oidc_provider.sessions import OidcSessionRevoker

    revoker = OidcSessionRevoker(uow_factory=uow_factory, clock=clock)
    await revoker.revoke_subject_sessions("u-1", "identity.user_banned.v1")

    # Families for the subject are revoked, so refresh is refused.
    async with uow_factory() as uow:
        families = (await uow.session.execute(select(OidcRefreshFamily))).scalars().all()
        assert families
        assert all(f.revoked_at is not None for f in families)

    with pytest.raises(OidcError) as excinfo:
        await TokenService(ctx).refresh(
            client_id="spa",
            refresh_token=tokens["refresh_token"],
        )
    assert excinfo.value.code == "invalid_grant"


def _security_envelope(ctx: ServiceContext, key: str, subject: str) -> Any:
    from inc.kernel.events import EventEnvelope

    return EventEnvelope(
        event_id=uuid.uuid7(),
        event_key=key,
        occurred_at=ctx.clock.utc_now(),
        producer="identity",
        payload={"subject_id": subject},
    )


async def test_key_rotation_keeps_old_key_verifying(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    await register_clients(client_ctx)
    tokens = await _authorize_and_exchange(ctx)

    await ctx.keys.rotate()
    jwks = await ctx.keys.public_jwks()
    assert len(jwks["keys"]) >= 2  # old key retained for verification

    public_keys = {entry["kid"]: load_public_key(entry) for entry in jwks["keys"]}
    old_claims = verify_jwt(
        tokens["id_token"], public_keys=public_keys, audience="spa", issuer=ISSUER
    )
    assert old_claims["sub"] == "u-1"


async def test_diagnostics_report_no_active_key_as_failed(
    ctx: ServiceContext,
    uow_factory: UoWFactory,
    clock: Any,
) -> None:
    # No keys generated yet: diagnostics must report failed.
    diagnostics = OidcDiagnostics(uow_factory=uow_factory, clock=clock)
    results = await diagnostics.run()
    assert any(
        r.code == "oidc.no_active_signing_key" and r.status.value == "failed" for r in results
    )


async def test_unsupported_response_type_rejected(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    """response_type outside the server-supported set (e.g. implicit id_token)
    must be rejected even if a client's registration lists it."""
    from sqlalchemy import update

    from inc.capabilities.oidc_provider.models import OidcClient
    from inc.capabilities.oidc_provider.services import (
        SUPPORTED_RESPONSE_TYPES,
        AuthorizationService,
    )

    assert SUPPORTED_RESPONSE_TYPES == ("code",)
    await RegisterClient(client_ctx)(
        name="Implicit",
        client_type="public",
        redirect_uris=[REDIRECT_URI],
        client_id="implicit-client",
    )

    async with ctx.uow_factory() as uow:
        await uow.session.execute(
            update(OidcClient)
            .where(OidcClient.client_id == "implicit-client")
            .values(response_types=StringList(items=["id_token", "code"]))
        )
        await uow.commit()

    _, challenge = _pkce_pair()
    with pytest.raises(OidcError) as excinfo:
        await AuthorizationService(ctx).issue_code(
            client_id="implicit-client",
            redirect_uri=REDIRECT_URI,
            response_type="id_token",
            scope=SCOPES,
            state="st",
            nonce="n",
            code_challenge=challenge,
            code_challenge_method="S256",
            subject_id="u-1",
            session_handle=None,
        )
    assert excinfo.value.code == "unsupported_response_type"


async def test_grant_type_enforced_for_exchange_and_refresh(
    ctx: ServiceContext,
    client_ctx: ClientCommandContext,
) -> None:
    """A client not registered for a grant type must not be able to use it,
    even if it somehow obtained a code / refresh token."""
    from sqlalchemy import update

    from inc.capabilities.oidc_provider.models import OidcClient

    await register_clients(client_ctx)

    # A confidential client with refresh disabled.
    no_refresh = await RegisterClient(client_ctx)(
        name="No Refresh",
        client_type="confidential",
        redirect_uris=["https://app.example.com/cb"],
        allowed_scopes=["openid", "profile", "email", "offline_access"],
        allow_refresh=False,
        client_id="no-refresh",
    )

    # Exchange is rejected when authorization_code grant is not registered.
    async with ctx.uow_factory() as uow:
        await uow.session.execute(
            update(OidcClient)
            .where(OidcClient.client_id == "no-refresh")
            .values(grant_types=StringList(items=["refresh_token"]))
        )
        await uow.commit()

    verifier, challenge = _pkce_pair()
    code = await AuthorizationService(ctx).issue_code(
        client_id="no-refresh",
        redirect_uri="https://app.example.com/cb",
        response_type="code",
        scope=SCOPES,
        state="st",
        nonce="n",
        code_challenge=challenge,
        code_challenge_method="S256",
        subject_id="u-1",
        session_handle=None,
    )
    raw_code = code.split("code=")[1].split("&")[0]
    with pytest.raises(OidcError) as excinfo:
        await TokenService(ctx).exchange(
            client_id="no-refresh",
            code=raw_code,
            redirect_uri="https://app.example.com/cb",
            code_verifier=verifier,
            client_secret=no_refresh.client_secret,
        )
    assert excinfo.value.code == "unauthorized_client"

    # Refresh is rejected when the client is not registered for it.
    tokens = await _authorize_and_exchange(ctx, client_id="spa")
    assert tokens.get("refresh_token") is not None

    async with ctx.uow_factory() as uow:
        await uow.session.execute(
            update(OidcClient)
            .where(OidcClient.client_id == "spa")
            .values(grant_types=StringList(items=["authorization_code"]))
        )
        await uow.commit()

    with pytest.raises(OidcError) as excinfo:
        await TokenService(ctx).refresh(
            client_id="spa",
            refresh_token=tokens["refresh_token"],
        )
    assert excinfo.value.code == "unauthorized_client"


async def test_client_auth_method_is_required_and_never_defaults_to_none(
    client_ctx: ClientCommandContext,
) -> None:
    """auth_method must be explicit at the boundary: a confidential client can
    never silently degrade to unauthenticated (none) access."""

    confidential = await RegisterClient(client_ctx)(
        name="Confidential",
        client_type="confidential",
        redirect_uris=["https://app.example.com/cb"],
    )
    assert confidential.client.auth_method == "client_secret_basic"
    assert confidential.client_secret is not None

    public = await RegisterClient(client_ctx)(
        name="Public",
        client_type="public",
        redirect_uris=["https://app.example.com/cb"],
    )
    assert public.client.auth_method == "none"
    assert public.client_secret is None

    from pydantic import ValidationError

    from inc.capabilities.oidc_provider.schemas import ClientDTO

    # The DTO no longer defaults to "none": omitting it is a loud failure.
    with pytest.raises(ValidationError):
        ClientDTO(
            client_id="c-1",
            client_type="confidential",
            name="x",
            redirect_uris=["https://app.example.com/cb"],
            allowed_scopes=["openid"],
        )
