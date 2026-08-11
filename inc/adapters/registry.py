"""Port adapters and adapter registry.

Contract source: context/spec/composition.md §4.

Adapters implement consumer-defined Ports using the provider capability's
public queries/commands only (imported from capability package roots).
Each manifest binds a Port to exactly one adapter key; missing or
duplicate bindings fail startup.
"""

from __future__ import annotations

import uuid
from typing import Any

from inc.capabilities.access import AuthorizeService
from inc.capabilities.access.schemas import Principal
from inc.capabilities.content import ContentQueries
from inc.capabilities.identity import CredentialAuthenticator, IdentityQueries
from inc.capabilities.oidc_provider import OidcSessionRevoker
from inc.capabilities.oidc_provider.ports import (
    AuthorizationDecisionReader,
    SubjectAuthenticator,
    SubjectClaimsReader,
)
from inc.kernel.errors import ErrorCategory, KernelError

ALLOWED_CLAIMS = ("sub", "name", "email", "email_verified", "preferred_username")


class IdentityCredentialAuthenticator(SubjectAuthenticator):
    """Local username/email + password login."""

    def __init__(self, *, authenticator: CredentialAuthenticator) -> None:
        self._authenticator = authenticator

    async def authenticate(self, username: str, password: str) -> str | None:
        subject = await self._authenticator.authenticate_local(username, password)
        return subject.id if subject is not None else None


class IdentityClaimsReader(SubjectClaimsReader):
    """Minimal profile claims allowed by the authorized scopes."""

    def __init__(self, *, queries: IdentityQueries) -> None:
        self._queries = queries

    async def claims_for(self, subject_id: str, scopes: set[str]) -> dict[str, Any]:
        subject = await self._queries.get_subject(subject_id)
        if subject is None:
            return {}
        claims: dict[str, Any] = {}
        if "openid" in scopes:
            claims["sub"] = subject_id
        if "profile" in scopes:
            claims["name"] = subject.display_name or subject.username
            claims["preferred_username"] = subject.username
        if "email" in scopes and subject.email_verified:
            claims["email"] = subject.email
            claims["email_verified"] = True
        return {k: v for k, v in claims.items() if k in ALLOWED_CLAIMS}


class AccessAuthorizationReader(AuthorizationDecisionReader):
    """Scope grants are backed by the access capability's roles/grants.

    openid is always granted to an authenticated subject; profile/email
    require the identity.read grant; the admin scope requires content
    management grants. The access capability remains the final boundary
    for every business endpoint.
    """

    def __init__(self, *, authorize: AuthorizeService) -> None:
        self._authorize = authorize

    async def can_grant(self, subject_id: str, client_id: str, scopes: set[str]) -> bool:
        required = _scope_capabilities(scopes)
        if required is None:
            return False  # unknown scopes are never silently granted
        principal = Principal(subject_id=subject_id, status="active", client_id=client_id)
        capabilities = await self._authorize.capabilities_of(principal)
        return required <= capabilities


def _scope_capabilities(scopes: set[str]) -> set[str] | None:
    """Scope -> capability policy; None means the scope set is not grantable.

    openid is always granted to an authenticated subject; profile/email
    require the identity read grant. Unknown scopes are rejected instead
    of being silently accepted.
    """

    out: set[str] = set()
    for scope in scopes:
        if scope == "openid":
            continue
        if scope in ("profile", "email"):
            out.add("identity.users.read")
        else:
            return None
    return out


class TaxonomyContentExists:
    """Target existence check implemented over the content capability.

    The opaque taxonomy ``target_type`` is interpreted as a content type
    name: a target exists when the content row exists and its
    ``type_name`` matches (the post feature declares
    ``target_types=("post",)``).
    """

    def __init__(self, *, queries: ContentQueries) -> None:
        self._queries = queries

    async def __call__(self, target_type: str, target_id: str) -> bool:
        parsed = _parse_uuid(target_id)
        if parsed is None:
            return False
        content = await self._queries.get(parsed)
        return content is not None and content.type_name == target_type


class ContentBatchExists:
    """Bulk existence for taxonomy orphan diagnostics."""

    def __init__(self, *, queries: ContentQueries) -> None:
        self._queries = queries

    async def __call__(self, target_type: str, target_ids: list[str]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for target_id in target_ids:
            parsed = _parse_uuid(target_id)
            content = await self._queries.get(parsed) if parsed is not None else None
            out[target_id] = content is not None and content.type_name == target_type
        return out


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def resolve_adapters(
    container: Any,
    *,
    bindings: tuple[tuple[str, str], ...],
    authenticator: CredentialAuthenticator,
    identity_queries: IdentityQueries,
    authorize: AuthorizeService,
    content_queries: ContentQueries | None,
    session_revoker: OidcSessionRevoker | None,
    settings_queries: Any,
) -> dict[str, Any]:
    """Resolve manifest (port, adapter) bindings into concrete objects."""

    resolved: dict[str, Any] = {}
    for port, adapter in bindings:
        if port in resolved:
            raise KernelError(
                code="kernel.port_duplicate",
                category=ErrorCategory.INTERNAL,
                message=f"port {port} bound more than once",
            )
        if adapter == "identity.credential":
            resolved[port] = IdentityCredentialAuthenticator(authenticator=authenticator)
        elif adapter == "identity.profile":
            resolved[port] = IdentityClaimsReader(queries=identity_queries)
        elif adapter == "access.authorize":
            resolved[port] = AccessAuthorizationReader(authorize=authorize)
        elif adapter == "oidc.session_revoker":
            resolved[port] = session_revoker
        elif adapter == "content.exists":
            resolved[port] = TaxonomyContentExists(queries=content_queries)  # type: ignore[arg-type]
        elif adapter == "content.batch_exists":
            resolved[port] = ContentBatchExists(queries=content_queries)  # type: ignore[arg-type]
        elif adapter == "assets.s3":
            from inc.adapters.assets import S3ObjectStorage

            resolved[port] = S3ObjectStorage(
                settings_queries=settings_queries, clock=container._clock
            )
        elif adapter == "payments.dev_fake":
            from inc.adapters.payments.dev_fake import DevFakePaymentProvider

            resolved[port] = DevFakePaymentProvider()
        elif adapter == "membership.subject_exists":
            from inc.adapters.membership import IdentitySubjectExists

            resolved[port] = IdentitySubjectExists(queries=identity_queries)
        elif adapter == "membership.points_ledger":
            from inc.adapters.membership import PointsGrantLedger

            resolved[port] = PointsGrantLedger(
                uow_factory=container._uow_factory,
                clock=container._clock,
                outbox=container._outbox,
                behaviors=container.behaviors,
            )
        else:
            raise KernelError(
                code="kernel.adapter_unknown",
                category=ErrorCategory.INTERNAL,
                message=f"unknown adapter {adapter!r} for port {port}",
            )
    return resolved
