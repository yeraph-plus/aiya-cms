"""Admin client registration commands.

Contract source: context/spec/capabilities/oidc-provider.md §9.

First version supports static, admin-managed registration only; no Dynamic
Client Registration protocol is exposed. Redirect URIs are exact strings,
never wildcards.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from inc.capabilities.oidc_provider.models import (
    OidcClient,
    OidcClientSecret,
    StringList,
)
from inc.capabilities.oidc_provider.schemas import (
    ClientDTO,
    ClientRegistrationResult,
    OidcError,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ClientCommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    audit_actor_id: str | None = None
    audit_trace_id: str | None = None


def _require_valid_redirect_uri(value: str) -> None:
    """Validate an exact redirect URI.

    Redirect URIs are exact strings, never wildcards or fragments. Only
    https with a host, or http for loopback hosts, are accepted.
    """

    if "*" in value or "#" in value:
        raise OidcError(
            "invalid_request", "redirect uri must be exact, with no wildcard or fragment"
        )
    parts = urlsplit(value)
    if parts.scheme == "https" and parts.netloc:
        return
    if parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS:
        return
    raise OidcError("invalid_request", "redirect uri must be https (or http://localhost)")


def _to_dto(client: OidcClient) -> ClientDTO:
    return ClientDTO(
        client_id=client.client_id,
        client_type=client.client_type,
        name=client.name,
        redirect_uris=list(client.redirect_uris.items),
        post_logout_redirect_uris=list(client.post_logout_redirect_uris.items),
        allowed_scopes=list(client.allowed_scopes.items),
        allowed_audiences=list(client.allowed_audiences.items),
        auth_method=client.auth_method,
        grant_types=list(client.grant_types.items),
        response_types=list(client.response_types.items),
        status=client.status,
        trusted=client.trusted,
        allow_refresh=client.allow_refresh,
    )


async def _append_audit(
    uow: UnitOfWork,
    ctx: ClientCommandContext,
    *,
    action: str,
    client_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=ctx.clock.utc_now(),
            producer="oidc_provider",
            aggregate_type="oidc",
            aggregate_id=client_id,
            trace_id=ctx.audit_trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": ctx.clock.utc_now().isoformat(),
                "actor_type": "user" if ctx.audit_actor_id else None,
                "actor_id": ctx.audit_actor_id,
                "client_id": client_id,
                "target_type": "oidc_client",
                "target_id": client_id,
                "trace_id": ctx.audit_trace_id,
                "details": details or {},
            },
        ),
    )


class RegisterClient:
    """Creates a static client; a confidential secret is shown once."""

    def __init__(self, ctx: ClientCommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self,
        *,
        name: str,
        client_type: str,
        redirect_uris: list[str],
        post_logout_redirect_uris: list[str] | None = None,
        allowed_scopes: list[str] | None = None,
        allowed_audiences: list[str] | None = None,
        trusted: bool = False,
        allow_refresh: bool = True,
        client_id: str | None = None,
    ) -> ClientRegistrationResult:
        if client_type not in ("public", "confidential"):
            raise OidcError("invalid_request", "client_type must be public or confidential")
        if not redirect_uris:
            raise OidcError("invalid_request", "at least one redirect uri is required")
        for uri in redirect_uris + (post_logout_redirect_uris or []):
            _require_valid_redirect_uri(uri)
        scopes = allowed_scopes or ["openid", "profile", "email"]
        unknown_scopes = set(scopes) - {"openid", "profile", "email", "offline_access"}
        if unknown_scopes:
            raise OidcError(
                "invalid_scope", f"unsupported scopes: {', '.join(sorted(unknown_scopes))}"
            )

        unique_client_id = client_id or f"client-{secrets.token_hex(8)}"
        client_secret: str | None = None
        async with self._ctx.uow_factory() as uow:
            client = OidcClient(
                client_id=unique_client_id,
                client_type=client_type,
                name=name,
                redirect_uris=StringList(items=redirect_uris),
                post_logout_redirect_uris=StringList(items=post_logout_redirect_uris or []),
                allowed_scopes=StringList(items=scopes),
                allowed_audiences=StringList(items=allowed_audiences or []),
                auth_method="client_secret_basic" if client_type == "confidential" else "none",
                grant_types=StringList(items=["authorization_code", "refresh_token"]),
                response_types=StringList(items=["code"]),
                status="active",
                trusted=trusted,
                allow_refresh=allow_refresh,
            )
            uow.session.add(client)
            if client_type == "confidential":
                client_secret = secrets.token_urlsafe(48)
                uow.session.add(
                    OidcClientSecret(
                        client_id=unique_client_id,
                        secret_digest=_digest(client_secret),
                        version=1,
                        expires_at=None,
                    )
                )
            await _append_audit(
                uow,
                self._ctx,
                action="oidc.client.registered",
                client_id=unique_client_id,
                details={"name": name, "client_type": client_type, "redirect_uris": redirect_uris},
            )
            await uow.commit()
            return ClientRegistrationResult(client=_to_dto(client), client_secret=client_secret)


class DisableClient:
    def __init__(self, ctx: ClientCommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, client_id: str) -> ClientDTO:  # type: ignore[return]
        async with self._ctx.uow_factory() as uow:
            client = (
                (
                    await uow.session.execute(
                        select(OidcClient).where(OidcClient.client_id == client_id)
                    )
                )
                .scalars()
                .first()
            )
            if client is None:
                raise OidcError("invalid_request", "unknown client")
            client.status = "disabled"
            await _append_audit(
                uow,
                self._ctx,
                action="oidc.client.disabled",
                client_id=client_id,
            )
            await uow.commit()
            return _to_dto(client)
