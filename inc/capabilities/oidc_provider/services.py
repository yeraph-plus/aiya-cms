"""OIDC protocol services: authorize, token, userinfo, revoke, logout.

Contract source: context/spec/capabilities/oidc-provider.md §6-§9.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any

import jwt as pyjwt
from sqlalchemy import select, update

from inc.capabilities.oidc_provider.keys import KeyService, load_public_key, sign_jwt, verify_jwt
from inc.capabilities.oidc_provider.models import (
    OidcAuthorizationCode,
    OidcClient,
    OidcClientSecret,
    OidcGrantConsent,
    OidcRefreshFamily,
    OidcRefreshToken,
    OidcSession,
    OidcSigningKey,
    StringList,
)
from inc.capabilities.oidc_provider.ports import (
    AuthorizationDecisionReader,
    SubjectAuthenticator,
    SubjectClaimsReader,
)
from inc.capabilities.oidc_provider.schemas import IntrospectionResult, OidcError, TokenResponse
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"
SESSION_COOKIE_NAME = "aiya_oidc_session"

SUPPORTED_SCOPES = ("openid", "profile", "email", "offline_access")
SUPPORTED_RESPONSE_TYPES = ("code",)
SUPPORTED_GRANT_TYPES = ("authorization_code", "refresh_token")
SUPPORTED_CLAIMS = ("sub", "name", "email", "email_verified", "preferred_username")
SUPPORTED_AMR = ("pwd",)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ensure_utc(value: Any) -> Any:
    """SQLite drops tzinfo; persisted times are always UTC."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _pkce_s256(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("utf-8")).digest())


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _new_opaque() -> str:
    return secrets.token_urlsafe(48)


def _constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


@dataclass(frozen=True, slots=True)
class ServiceContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    keys: KeyService
    authenticator: SubjectAuthenticator
    claims_reader: SubjectClaimsReader
    authorization_reader: AuthorizationDecisionReader
    issuer: str
    audit_trace_id: str | None = None
    code_lifetime_seconds: int = 600
    id_token_lifetime_seconds: int = 600
    access_token_lifetime_seconds: int = 300
    refresh_absolute_lifetime_seconds: int = 30 * 24 * 3600
    refresh_inactivity_lifetime_seconds: int = 7 * 24 * 3600


async def _append_audit(
    uow: UnitOfWork,
    ctx: ServiceContext,
    *,
    action: str,
    client_id: str,
    subject_id: str | None,
    details: Mapping[str, Any] | None = None,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=ctx.clock.utc_now(),
            producer="oidc_provider",
            aggregate_type="oidc",
            aggregate_id=subject_id or client_id,
            trace_id=ctx.audit_trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": ctx.clock.utc_now().isoformat(),
                "actor_type": "user" if subject_id else "client",
                "actor_id": subject_id or client_id,
                "client_id": client_id,
                "target_type": "oidc",
                "target_id": subject_id or client_id,
                "trace_id": ctx.audit_trace_id,
                "details": dict(details or {}),
            },
        ),
    )


async def _client_by_id(uow: UnitOfWork, client_id: str) -> OidcClient | None:
    client: OidcClient | None = (
        (await uow.session.execute(select(OidcClient).where(OidcClient.client_id == client_id)))
        .scalars()
        .first()
    )
    return client


async def _authenticate_client(
    uow: UnitOfWork,
    client: OidcClient,
    *,
    client_secret: str | None,
    now: Any,
) -> None:
    if client.status != "active":
        raise OidcError("invalid_client", "client is not active")
    if client.auth_method == "none":
        if client_secret is not None:
            raise OidcError("invalid_client", "public client must not send a secret")
        return
    if client.auth_method != "client_secret_basic":
        raise OidcError("invalid_client", "unsupported client authentication method")
    if client_secret is None:
        raise OidcError("invalid_client", "client secret required")
    row = (
        (
            await uow.session.execute(
                select(OidcClientSecret)
                .where(
                    OidcClientSecret.client_id == client.client_id,
                    OidcClientSecret.revoked_at.is_(None),
                    (OidcClientSecret.expires_at.is_(None)) | (OidcClientSecret.expires_at > now),
                )
                .order_by(OidcClientSecret.version.desc())
            )
        )
        .scalars()
        .first()
    )
    if row is None or not _constant_time_equal(row.secret_digest, _digest(client_secret)):
        raise OidcError("invalid_client", "client authentication failed")


class AuthorizationService:
    """Validates authorize requests and issues one-time codes."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    async def issue_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        response_type: str,
        scope: str,
        state: str | None,
        nonce: str | None,
        code_challenge: str | None,
        code_challenge_method: str | None,
        subject_id: str,
        session_handle: str | None,
    ) -> str:
        scopes = _parse_scopes(scope)
        if "openid" not in scopes:
            raise OidcError("invalid_scope", "openid scope is required")
        unknown = scopes - set(SUPPORTED_SCOPES)
        if unknown:
            raise OidcError("invalid_scope", f"unsupported scopes: {', '.join(sorted(unknown))}")

        async with self._ctx.uow_factory() as uow:
            client = await _client_by_id(uow, client_id)
            if client is None or client.status != "active":
                raise OidcError("invalid_request", "unknown or disabled client")
            if redirect_uri not in client.redirect_uris.items:
                raise OidcError("invalid_request", "redirect uri is not registered")
            if response_type not in SUPPORTED_RESPONSE_TYPES:
                raise OidcError(
                    "unsupported_response_type", "response_type is not supported by this server"
                )
            if response_type not in client.response_types.items:
                raise OidcError("unsupported_response_type", "unsupported response type")
            if not scopes.issubset(set(client.allowed_scopes.items)):
                raise OidcError("invalid_scope", "scope exceeds client registration")
            if code_challenge is None or code_challenge_method != "S256":
                raise OidcError("invalid_request", "PKCE code_challenge with S256 is required")
            if not await self._ctx.authorization_reader.can_grant(subject_id, client_id, scopes):
                raise OidcError(
                    "access_denied", "subject is not authorized for the requested scope"
                )

            code = _new_opaque()
            uow.session.add(
                OidcAuthorizationCode(
                    code_digest=_digest(code),
                    client_id=client.client_id,
                    subject_id=subject_id,
                    redirect_uri=redirect_uri,
                    scopes=StringList(items=list(scopes)),
                    audiences=StringList(items=list(client.allowed_audiences.items)),
                    nonce=nonce,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    expires_at=self._ctx.clock.utc_now()
                    + timedelta(seconds=self._ctx.code_lifetime_seconds),
                )
            )
            await _append_audit(
                uow,
                self._ctx,
                action="oidc.authorization.code_issued",
                client_id=client.client_id,
                subject_id=subject_id,
                details={"redirect_uri": redirect_uri},
            )
            await uow.commit()

        query = {"code": code}
        if state is not None:
            query["state"] = state
        joined = "&".join(f"{k}={_quote(v)}" for k, v in query.items())
        return f"{redirect_uri}?{joined}"


class TokenService:
    """Code exchange, token issuance and refresh rotation."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    async def exchange(  # type: ignore[return]
        self,
        *,
        client_id: str,
        code: str,
        redirect_uri: str,
        code_verifier: str | None,
        client_secret: str | None = None,
    ) -> TokenResponse:
        async with self._ctx.uow_factory() as uow:
            client = await _client_by_id(uow, client_id)
            if client is None:
                raise OidcError("invalid_client", "unknown client")
            await _authenticate_client(
                uow, client, client_secret=client_secret, now=self._ctx.clock.utc_now()
            )
            if "authorization_code" not in client.grant_types.items:
                raise OidcError(
                    "unauthorized_client",
                    "client is not registered for the authorization_code grant",
                )

            row = (
                (
                    await uow.session.execute(
                        select(OidcAuthorizationCode).where(
                            OidcAuthorizationCode.code_digest == _digest(code)
                        )
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                raise OidcError("invalid_grant", "invalid authorization code")
            if row.consumed_at is not None:
                await _append_audit(
                    uow,
                    self._ctx,
                    action="oidc.token.code_replay",
                    client_id=client.client_id,
                    subject_id=row.subject_id,
                    details={"code_id": str(row.id)},
                )
                # The replay-detection audit must survive the error: the UoW
                # would otherwise roll it back when the exception propagates.
                await uow.commit()
                raise OidcError("invalid_grant", "authorization code already used")
            if _ensure_utc(row.expires_at) < self._ctx.clock.utc_now():
                raise OidcError("invalid_grant", "authorization code expired")
            if row.client_id != client.client_id:
                raise OidcError("invalid_grant", "code was issued to another client")
            if row.redirect_uri != redirect_uri:
                raise OidcError("invalid_grant", "redirect uri mismatch")
            if row.code_challenge is not None:
                if code_verifier is None or not _constant_time_equal(
                    _pkce_s256(code_verifier), row.code_challenge
                ):
                    raise OidcError("invalid_grant", "PKCE verification failed")
            elif code_verifier is not None:
                raise OidcError("invalid_grant", "unexpected code verifier without challenge")

            row.consumed_at = self._ctx.clock.utc_now()
            # Consume the code atomically so a concurrent exchange cannot
            # redeem the same code twice.
            consumed = await uow.session.execute(
                update(OidcAuthorizationCode)
                .where(
                    OidcAuthorizationCode.id == row.id,
                    OidcAuthorizationCode.consumed_at.is_(None),
                )
                .values(consumed_at=self._ctx.clock.utc_now())
                .execution_options(synchronize_session=False)
            )
            if consumed.rowcount != 1:
                await _append_audit(
                    uow,
                    self._ctx,
                    action="oidc.token.code_replay",
                    client_id=client.client_id,
                    subject_id=row.subject_id,
                    details={"code_id": str(row.id)},
                )
                await uow.commit()
                raise OidcError("invalid_grant", "authorization code already used")
            await self._ensure_grant(uow, client, row)
            session = await self._ensure_session(uow, client, row.subject_id)
            tokens = await self._issue_tokens(
                uow, client, row.subject_id, set(row.scopes.items), session, nonce=row.nonce
            )
            await _append_audit(
                uow,
                self._ctx,
                action="oidc.token.issued",
                client_id=client.client_id,
                subject_id=row.subject_id,
                details={"scopes": row.scopes.items},
            )
            await uow.commit()
            return tokens

    async def refresh(  # type: ignore[return]
        self,
        *,
        client_id: str,
        refresh_token: str,
        client_secret: str | None = None,
    ) -> TokenResponse:
        async with self._ctx.uow_factory() as uow:
            client = await _client_by_id(uow, client_id)
            if client is None:
                raise OidcError("invalid_client", "unknown client")
            await _authenticate_client(
                uow, client, client_secret=client_secret, now=self._ctx.clock.utc_now()
            )
            if "refresh_token" not in client.grant_types.items or not client.allow_refresh:
                raise OidcError(
                    "unauthorized_client", "client is not registered for the refresh_token grant"
                )

            token = (
                (
                    await uow.session.execute(
                        select(OidcRefreshToken).where(
                            OidcRefreshToken.token_digest == _digest(refresh_token)
                        )
                    )
                )
                .scalars()
                .first()
            )
            if token is None:
                raise OidcError("invalid_grant", "invalid refresh token")
            family = await uow.session.get(OidcRefreshFamily, token.family_id)
            if family is None or family.revoked_at is not None or token.revoked_at is not None:
                raise OidcError("invalid_grant", "refresh token revoked")
            if family.client_id != client.client_id:
                raise OidcError("invalid_grant", "refresh token issued to another client")
            if token.rotated_at is not None:
                # Reuse of an already-rotated token: revoke the whole family.
                family.revoked_at = self._ctx.clock.utc_now()
                token.reused_at = self._ctx.clock.utc_now()
                await _append_audit(
                    uow,
                    self._ctx,
                    action="oidc.refresh.reuse_detected",
                    client_id=client.client_id,
                    subject_id=family.subject_id,
                    details={"family_id": str(family.id)},
                )
                await uow.commit()
                raise OidcError("invalid_grant", "refresh token reuse detected")
            now = self._ctx.clock.utc_now()
            if (
                _ensure_utc(token.expires_at) < now
                or _ensure_utc(token.inactivity_expires_at) < now
            ):
                raise OidcError("invalid_grant", "refresh token expired")
            # Rotate the token atomically: only the first caller wins, so a
            # concurrent reuse of the same token cannot mint two successors.
            rotated = await uow.session.execute(
                update(OidcRefreshToken)
                .where(
                    OidcRefreshToken.id == token.id,
                    OidcRefreshToken.rotated_at.is_(None),
                )
                .values(
                    rotated_at=now,
                    last_used_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if rotated.rowcount != 1:
                # A concurrent rotation already won; the reused token is a theft
                # signal, so revoke the whole family.
                family.revoked_at = now
                token.reused_at = now
                await _append_audit(
                    uow,
                    self._ctx,
                    action="oidc.refresh.reuse_detected",
                    client_id=client.client_id,
                    subject_id=family.subject_id,
                    details={"family_id": str(family.id)},
                )
                await uow.commit()
                raise OidcError("invalid_grant", "refresh token reuse detected")
            token.rotated_at = now
            token.last_used_at = now
            new_token = _new_opaque()
            uow.session.add(
                OidcRefreshToken(
                    family_id=family.id,
                    token_digest=_digest(new_token),
                    generation=token.generation + 1,
                    scopes=token.scopes,
                    audiences=token.audiences,
                    expires_at=token.expires_at,
                    inactivity_expires_at=now
                    + timedelta(seconds=self._ctx.refresh_inactivity_lifetime_seconds),
                )
            )
            session = await self._ensure_session(uow, client, family.subject_id)
            tokens = await self._issue_tokens(
                uow, client, family.subject_id, set(token.scopes.items), session
            )
            tokens.refresh_token = new_token
            await _append_audit(
                uow,
                self._ctx,
                action="oidc.refresh.rotated",
                client_id=client.client_id,
                subject_id=family.subject_id,
                details={"generation": token.generation + 1},
            )
            await uow.commit()
            return tokens

    async def introspect_refresh(self, refresh_token: str) -> IntrospectionResult:  # type: ignore[return]
        async with self._ctx.uow_factory() as uow:
            token = (
                (
                    await uow.session.execute(
                        select(OidcRefreshToken).where(
                            OidcRefreshToken.token_digest == _digest(refresh_token)
                        )
                    )
                )
                .scalars()
                .first()
            )
            if token is None:
                return IntrospectionResult(active=False)
            family = await uow.session.get(OidcRefreshFamily, token.family_id)
            active = (
                token.revoked_at is None
                and token.rotated_at is None
                and family is not None
                and family.revoked_at is None
                and _ensure_utc(token.expires_at) >= self._ctx.clock.utc_now()
                and _ensure_utc(token.inactivity_expires_at) >= self._ctx.clock.utc_now()
            )
            return IntrospectionResult(
                active=active,
                subject_id=family.subject_id if family else None,
                client_id=family.client_id if family else None,
            )

    async def _ensure_grant(
        self, uow: UnitOfWork, client: OidcClient, code: OidcAuthorizationCode
    ) -> None:
        grant = (
            (
                await uow.session.execute(
                    select(OidcGrantConsent).where(
                        OidcGrantConsent.subject_id == code.subject_id,
                        OidcGrantConsent.client_id == client.client_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        scopes = list(set(code.scopes.items))
        if grant is None:
            uow.session.add(
                OidcGrantConsent(
                    subject_id=code.subject_id,
                    client_id=client.client_id,
                    scopes=StringList(items=scopes),
                    audiences=code.audiences,
                    granted_at=self._ctx.clock.utc_now(),
                )
            )
        elif grant.revoked_at is None:
            grant.scopes = StringList(items=list(set(grant.scopes.items) | set(scopes)))
        else:
            grant.revoked_at = None
            grant.scopes = StringList(items=scopes)
            grant.granted_at = self._ctx.clock.utc_now()

    async def _ensure_session(
        self, uow: UnitOfWork, client: OidcClient, subject_id: str
    ) -> OidcSession:
        session: OidcSession | None = (
            (
                await uow.session.execute(
                    select(OidcSession).where(
                        OidcSession.subject_id == subject_id,
                        OidcSession.client_id == client.client_id,
                        OidcSession.revoked_at.is_(None),
                        OidcSession.expires_at > self._ctx.clock.utc_now(),
                    )
                )
            )
            .scalars()
            .first()
        )
        if session is not None:
            return session
        handle = _new_opaque()
        session = OidcSession(
            subject_id=subject_id,
            client_id=client.client_id,
            session_handle=_digest(handle),
            auth_time=self._ctx.clock.utc_now(),
            acr="1",
            amr=StringList(items=["pwd"]),
            expires_at=self._ctx.clock.utc_now()
            + timedelta(seconds=self._ctx.refresh_absolute_lifetime_seconds),
        )
        uow.session.add(session)
        return session

    async def _issue_tokens(
        self,
        uow: UnitOfWork,
        client: OidcClient,
        subject_id: str,
        scopes: set[str],
        session: OidcSession,
        *,
        nonce: str | None = None,
    ) -> TokenResponse:
        key = await self._ctx.keys.ensure_active_key()
        now = self._ctx.clock.utc_now()

        claims = await self._ctx.claims_reader.claims_for(subject_id, scopes)
        id_claims: dict[str, Any] = {
            "iss": self._ctx.issuer,
            "sub": subject_id,
            "aud": client.client_id,
            "exp": int((now + timedelta(seconds=self._ctx.id_token_lifetime_seconds)).timestamp()),
            "iat": int(now.timestamp()),
            "auth_time": int(_ensure_utc(session.auth_time).timestamp()),
            "azp": client.client_id,
            "sid": session.session_handle,
            "amr": list(session.amr.items),
        }
        if nonce is not None:
            id_claims["nonce"] = nonce
        id_claims.update({k: v for k, v in claims.items() if k in SUPPORTED_CLAIMS and k != "sub"})

        access_claims: dict[str, Any] = {
            "iss": self._ctx.issuer,
            "sub": subject_id,
            "aud": [self._ctx.issuer] + list(client.allowed_audiences.items),
            "exp": int(
                (now + timedelta(seconds=self._ctx.access_token_lifetime_seconds)).timestamp()
            ),
            "iat": int(now.timestamp()),
            "scope": " ".join(sorted(scopes)),
            "client_id": client.client_id,
            "sid": session.session_handle,
        }

        response = TokenResponse(
            access_token=sign_jwt(key, access_claims),
            expires_in=self._ctx.access_token_lifetime_seconds,
            scope=" ".join(sorted(scopes)),
            id_token=sign_jwt(key, id_claims),
        )
        if client.allow_refresh and "offline_access" in scopes:
            family = OidcRefreshFamily(
                subject_id=subject_id,
                client_id=client.client_id,
            )
            uow.session.add(family)
            await uow.session.flush()
            token = _new_opaque()
            uow.session.add(
                OidcRefreshToken(
                    family_id=family.id,
                    token_digest=_digest(token),
                    generation=1,
                    scopes=StringList(items=list(scopes)),
                    audiences=client.allowed_audiences,
                    expires_at=now + timedelta(seconds=self._ctx.refresh_absolute_lifetime_seconds),
                    inactivity_expires_at=now
                    + timedelta(seconds=self._ctx.refresh_inactivity_lifetime_seconds),
                )
            )
            response.refresh_token = token
        return response


class UserInfoService:
    """Returns only the claims authorized by the presented access token."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    async def userinfo(self, bearer_token: str) -> dict[str, Any]:
        async with self._ctx.uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(OidcSigningKey).where(
                            (OidcSigningKey.delete_at.is_(None))
                            | (OidcSigningKey.delete_at > self._ctx.clock.utc_now())
                        )
                    )
                )
                .scalars()
                .all()
            )
        public_keys = {row.kid: load_public_key(row.public_jwk.model_dump()) for row in rows}
        claims = verify_jwt(
            bearer_token,
            public_keys=public_keys,
            audience=self._ctx.issuer,
            issuer=self._ctx.issuer,
        )
        scopes = set((claims.get("scope") or "").split())
        if "openid" not in scopes:
            raise OidcError("invalid_token", "token lacks openid scope")
        allowed = await self._ctx.claims_reader.claims_for(claims["sub"], scopes)
        return {"sub": claims["sub"], **{k: v for k, v in allowed.items() if k != "sub"}}


class RevocationService:
    """RFC 7009 revocation; unknown tokens are idempotent successes."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    async def revoke(
        self,
        *,
        client_id: str,
        token: str,
        token_type_hint: str | None,
        client_secret: str | None = None,
    ) -> None:
        async with self._ctx.uow_factory() as uow:
            client = await _client_by_id(uow, client_id)
            if client is None:
                raise OidcError("invalid_client", "unknown client")
            await _authenticate_client(
                uow, client, client_secret=client_secret, now=self._ctx.clock.utc_now()
            )

            refresh = (
                (
                    await uow.session.execute(
                        select(OidcRefreshToken).where(
                            OidcRefreshToken.token_digest == _digest(token)
                        )
                    )
                )
                .scalars()
                .first()
            )
            if refresh is not None:
                family = await uow.session.get(OidcRefreshFamily, refresh.family_id)
                if family is not None and family.client_id == client.client_id:
                    family.revoked_at = self._ctx.clock.utc_now()
                    refresh.revoked_at = self._ctx.clock.utc_now()
                    await _append_audit(
                        uow,
                        self._ctx,
                        action="oidc.token.revoked",
                        client_id=client.client_id,
                        subject_id=family.subject_id,
                    )
                    await uow.commit()
            # Access token (JWT): no session context available -> idempotent success.
            return


class LogoutService:
    """RP-Initiated Logout with exact redirect matching."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    async def logout(
        self,
        *,
        id_token_hint: str | None,
        post_logout_redirect_uri: str | None,
        session_cookie: str | None,
    ) -> str | None:
        subject_id: str | None = None
        client_id: str | None = None
        session_handle: str | None = None

        async with self._ctx.uow_factory() as uow:
            if session_cookie is not None:
                session_row = (
                    (
                        await uow.session.execute(
                            select(OidcSession).where(
                                OidcSession.session_handle == _digest(session_cookie)
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if session_row is not None:
                    session_row.revoked_at = self._ctx.clock.utc_now()
                    subject_id = session_row.subject_id
                    client_id = session_row.client_id
                    session_handle = session_row.session_handle

            if id_token_hint is not None:
                rows = (
                    (
                        await uow.session.execute(
                            select(OidcSigningKey).where(
                                (OidcSigningKey.delete_at.is_(None))
                                | (OidcSigningKey.delete_at > self._ctx.clock.utc_now())
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                public_keys = {
                    row.kid: load_public_key(row.public_jwk.model_dump()) for row in rows
                }
                hint_aud = _unverified_aud(id_token_hint)
                try:
                    claims = verify_jwt(
                        id_token_hint,
                        public_keys=public_keys,
                        audience=hint_aud or client_id or "",
                        issuer=self._ctx.issuer,
                    )
                except OidcError:
                    claims = {}
                if claims:
                    subject_id = subject_id or claims.get("sub")
                    client_id = client_id or claims.get("aud")
                    hint_sid = claims.get("sid")
                    if hint_sid:
                        session_row = (
                            (
                                await uow.session.execute(
                                    select(OidcSession).where(
                                        OidcSession.session_handle == hint_sid,
                                        OidcSession.revoked_at.is_(None),
                                    )
                                )
                            )
                            .scalars()
                            .first()
                        )
                        if session_row is not None:
                            session_row.revoked_at = self._ctx.clock.utc_now()
                            subject_id = session_row.subject_id
                            client_id = session_row.client_id
                            session_handle = session_row.session_handle

            if post_logout_redirect_uri is not None:
                if id_token_hint is None and session_handle is None:
                    raise OidcError(
                        "invalid_request", "post-logout redirect requires a valid hint or session"
                    )
                if client_id is None:
                    raise OidcError(
                        "invalid_request", "cannot resolve client for post-logout redirect"
                    )
                client = await _client_by_id(uow, client_id)
                if (
                    client is None
                    or post_logout_redirect_uri not in client.post_logout_redirect_uris.items
                ):
                    raise OidcError("invalid_request", "post-logout redirect uri is not registered")

            if client_id is not None:
                client = await _client_by_id(uow, client_id)
                if client is not None:
                    families = (
                        (
                            await uow.session.execute(
                                select(OidcRefreshFamily).where(
                                    OidcRefreshFamily.client_id == client.client_id,
                                    OidcRefreshFamily.subject_id == (subject_id or ""),
                                    OidcRefreshFamily.revoked_at.is_(None),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for family in families:
                        family.revoked_at = self._ctx.clock.utc_now()

            await _append_audit(
                uow,
                self._ctx,
                action="oidc.logout",
                client_id=client_id or "unknown",
                subject_id=subject_id,
            )
            await uow.commit()
        return post_logout_redirect_uri


def _parse_scopes(scope: str) -> set[str]:
    return {s for s in scope.split() if s}


def _unverified_aud(token: str) -> str | None:
    """Read the aud claim without verification to resolve the client."""

    try:
        claims = pyjwt.decode(token, options={"verify_signature": False})
    except Exception:  # noqa: BLE001 - unverified parsing is best-effort
        return None
    aud = claims.get("aud")
    return aud if isinstance(aud, str) else None


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
