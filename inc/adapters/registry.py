"""Port adapters and adapter registry.

Contract source: context/spec/composition.md §4.

Adapters implement consumer-defined Ports using the provider capability's
public queries/commands only (imported from capability package roots).
Each manifest binds a Port to exactly one adapter key; missing or
duplicate bindings fail startup.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from inc.capabilities.access import AuthorizeService
from inc.capabilities.access.schemas import Principal
from inc.capabilities.community.ports import CommunityAuthorPort
from inc.capabilities.community.schemas import CommunityAuthorDTO
from inc.capabilities.content import ContentQueries
from inc.capabilities.identity import CredentialAuthenticator, IdentityQueries
from inc.capabilities.notification.ports import RecipientTarget
from inc.capabilities.oidc_provider import OidcSessionRevoker
from inc.capabilities.oidc_provider.ports import (
    AuthorizationDecisionReader,
    SubjectAuthenticator,
    SubjectClaimsReader,
)
from inc.kernel.errors import ErrorCategory, KernelError

ALLOWED_CLAIMS = ("sub", "name", "email", "email_verified", "preferred_username")

# Port ownership and provider requirements are validated by the composition
# root before any concrete adapter is constructed.
PORT_CONTRACTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "oidc.subject_authenticator": ("oidc_provider", ("identity",)),
    "oidc.subject_claims": ("oidc_provider", ("identity",)),
    "oidc.authorization_decision": ("oidc_provider", ("access",)),
    "oidc.security_events": ("oidc_provider", ("oidc_provider",)),
    "oidc.signing_keys": ("oidc_provider", ()),
    "taxonomy.target_exists": ("taxonomy", ("content",)),
    "comments.target_exists": ("comments", ("content",)),
    "assets.object_storage": ("assets", ()),
    "payments.provider": ("payments", ()),
    "notification.email": ("notification", ("settings",)),
    "notification.recipient": ("notification", ("identity",)),
    "membership.subject_exists": ("membership", ("identity",)),
    "membership.points_ledger": ("membership", ("points",)),
    "community.author": ("community", ("identity",)),
}

ADAPTER_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "identity.credential": ("identity",),
    "identity.profile": ("identity",),
    "access.authorize": ("access",),
    "oidc.session_revoker": ("oidc_provider",),
    "oidc.in_memory_keys": (),
    "oidc.filesystem_keys": (),
    "content.exists": ("content",),
    "content.batch_exists": ("content",),
    "assets.s3": (),
    "payments.dev_fake": (),
    "payments.paypal": (),
    "email.smtp": ("settings",),
    "email.smtp2go": ("settings",),
    "identity.notification_recipient": ("identity",),
    "membership.subject_exists": ("identity",),
    "membership.points_ledger": ("points",),
    "identity.community_author": ("identity",),
}

KNOWN_ADAPTERS = frozenset(ADAPTER_REQUIREMENTS)
MULTI_PROVIDER_PORTS = frozenset({"notification.email"})

# Provider ports are deliberately kept separate from ordinary Port bindings.
# A manifest selects which ports are available, while the catalog registers
# every provider allowed for those ports.  The capability/feature layer can
# then resolve the active implementation from settings without importing an
# adapter module or rebuilding the container.
PROVIDER_ADAPTERS: dict[str, tuple[str, ...]] = {
    "notification.email": ("email.smtp", "email.smtp2go"),
    "payments.provider": ("payments.dev_fake", "payments.paypal"),
    "assets.object_storage": ("assets.s3",),
}


@dataclass(frozen=True, slots=True)
class ProviderRegistration[TProvider]:
    """One inert provider registration held by a container-local catalog."""

    key: str
    provider: TProvider


class ProviderCatalog[TProvider]:
    """Deterministic provider catalog frozen during application boot.

    This is intentionally a small composition primitive, not a global plugin
    registry.  Importing an adapter never registers anything; the API
    composition root creates and freezes one catalog per provider Port.
    """

    def __init__(self, port: str) -> None:
        self.port = port
        self._providers: dict[str, TProvider] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, key: str, provider: TProvider) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"provider catalog {self.port} is frozen; cannot register {key}",
            )
        if key in self._providers:
            raise KernelError(
                code="kernel.provider_duplicate",
                category=ErrorCategory.INTERNAL,
                message=f"provider {key!r} is already registered for {self.port}",
            )
        self._providers[key] = provider

    def freeze(self) -> None:
        self._frozen = True

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def registrations(self) -> tuple[ProviderRegistration[TProvider], ...]:
        return tuple(
            ProviderRegistration(key=key, provider=self._providers[key]) for key in self.keys()
        )

    def get(self, key: str) -> TProvider | None:
        return self._providers.get(key)

    def require(self, key: str) -> TProvider:
        provider = self.get(key)
        if provider is None:
            raise KernelError(
                code="kernel.provider_unknown",
                category=ErrorCategory.VALIDATION,
                message=f"provider {key!r} is not registered for {self.port}",
            )
        return provider


class ProviderResolver[TProvider]:
    """Resolve the provider selected by a settings field at call time."""

    def __init__(
        self,
        *,
        catalog: ProviderCatalog[TProvider],
        settings_queries: Any | None = None,
        settings_group: str | None = None,
        settings_field: str | None = None,
        default_key: str | None = None,
    ) -> None:
        self._catalog = catalog
        self._settings_queries = settings_queries
        self._settings_group = settings_group
        self._settings_field = settings_field
        self._default_key = default_key

    @property
    def catalog(self) -> ProviderCatalog[TProvider]:
        return self._catalog

    async def selected_key(self) -> str:
        value: Any = None
        if (
            self._settings_queries is not None
            and self._settings_group is not None
            and self._settings_field is not None
        ):
            try:
                value = await self._settings_queries.get_value(
                    self._settings_group, self._settings_field
                )
            except KernelError as exc:
                # A manifest without the settings feature uses the explicit
                # composition default.  Unknown groups/fields are not a
                # reason to silently select an arbitrary provider.
                if exc.code not in {"settings.unknown_group", "settings.unknown_field"}:
                    raise
        key = str(value).strip() if value is not None else ""
        if not key:
            key = self._default_key or (self._catalog.keys()[0] if self._catalog.keys() else "")
        self._catalog.require(key)
        return key

    async def resolve(self) -> TProvider:
        return self._catalog.require(await self.selected_key())

    async def resolve_many(self) -> tuple[TProvider, ...]:
        """Return the selected provider only, preserving a stable tuple Port."""

        return (await self.resolve(),)


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


class IdentityNotificationRecipient:
    """Resolve identity email targets without exposing identity persistence."""

    def __init__(self, *, queries: IdentityQueries) -> None:
        self._queries = queries

    async def resolve(
        self, recipient_type: str, recipient_id: str, channel: str
    ) -> RecipientTarget | None:
        if recipient_type != "identity" or channel != "email":
            return None
        try:
            subject = await self._queries.get_subject(recipient_id)
        except ValueError:
            return None
        if subject is None or subject.status != "active" or not subject.email:
            return None
        local, separator, domain = subject.email.partition("@")
        if not separator:
            masked = subject.email[:2] + "***"
        else:
            visible = local[:2] if len(local) > 2 else local[:1]
            masked = f"{visible}***@{domain}"
        return RecipientTarget(channel="email", address=subject.email, masked_address=masked)


class IdentityCommunityAuthor(CommunityAuthorPort):
    """Community author projection backed by identity's public query surface."""

    def __init__(self, *, queries: IdentityQueries) -> None:
        self._queries = queries

    async def validate(self, author_type: str, author_id: str) -> bool:
        if author_type != "identity":
            return False
        try:
            profile = await self._queries.get_public_profile(author_id)
        except ValueError:
            return False
        return profile is not None and not profile.deleted

    async def project(
        self, references: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], CommunityAuthorDTO]:
        projected: dict[tuple[str, str], CommunityAuthorDTO] = {}
        for author_type, author_id in references:
            if author_type != "identity":
                continue
            try:
                profile = await self._queries.get_public_profile(author_id)
            except ValueError:
                continue
            if profile is None:
                continue
            projected[(author_type, author_id)] = CommunityAuthorDTO(
                id=profile.id,
                username=profile.username,
                display_name=profile.display_name,
                avatar_asset_id=profile.avatar_asset_id,
                deleted=profile.deleted,
            )
        return projected

    async def validate_author(self, author_type: str, author_id: str) -> bool:
        return await self.validate(author_type, author_id)

    async def project_authors(
        self, references: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], CommunityAuthorDTO]:
        return await self.project(references)


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
        if port in resolved and port not in MULTI_PROVIDER_PORTS:
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
            if session_revoker is None:
                raise KernelError(
                    code="kernel.adapter_dependency_missing",
                    category=ErrorCategory.INTERNAL,
                    message="adapter 'oidc.session_revoker' requires the oidc_provider capability",
                )
            resolved[port] = session_revoker
        elif adapter == "oidc.in_memory_keys":
            from inc.capabilities.oidc_provider import InMemorySigningKeyStore

            resolved[port] = InMemorySigningKeyStore()
        elif adapter == "oidc.filesystem_keys":
            from inc.adapters.oidc import FileSigningKeyStore

            directory = getattr(container._settings, "oidc_signing_key_dir", None)
            resolved[port] = FileSigningKeyStore(directory or ".tmp/oidc-keys")
        elif adapter == "identity.notification_recipient":
            resolved[port] = IdentityNotificationRecipient(queries=identity_queries)
        elif adapter == "content.exists":
            if content_queries is None:
                raise KernelError(
                    code="kernel.adapter_dependency_missing",
                    category=ErrorCategory.INTERNAL,
                    message="adapter 'content.exists' requires the content capability",
                )
            resolved[port] = TaxonomyContentExists(queries=content_queries)
        elif adapter == "content.batch_exists":
            if content_queries is None:
                raise KernelError(
                    code="kernel.adapter_dependency_missing",
                    category=ErrorCategory.INTERNAL,
                    message="adapter 'content.batch_exists' requires the content capability",
                )
            resolved[port] = ContentBatchExists(queries=content_queries)
        elif adapter == "assets.s3":
            from inc.adapters.assets import S3ObjectStorage

            resolved[port] = S3ObjectStorage(
                settings_queries=settings_queries, clock=container._clock
            )
        elif adapter == "payments.dev_fake":
            from inc.adapters.payments.dev_fake import DevFakePaymentProvider

            resolved[port] = DevFakePaymentProvider()
        elif adapter == "payments.paypal":
            from inc.adapters.payments.paypal import PaypalPaymentProvider

            resolved[port] = PaypalPaymentProvider.from_settings(container._settings)
        elif adapter == "email.smtp":
            from inc.adapters.notification import SmtpEmailAdapter

            smtp_provider = SmtpEmailAdapter(settings_queries=settings_queries)
            resolved[port] = (*resolved.get(port, ()), smtp_provider)
        elif adapter == "email.smtp2go":
            from inc.adapters.notification import Smtp2GoEmailAdapter

            smtp2go_provider = Smtp2GoEmailAdapter(settings_queries=settings_queries)
            resolved[port] = (*resolved.get(port, ()), smtp2go_provider)
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
        elif adapter == "identity.community_author":
            resolved[port] = IdentityCommunityAuthor(queries=identity_queries)
        else:
            raise KernelError(
                code="kernel.adapter_unknown",
                category=ErrorCategory.INTERNAL,
                message=f"unknown adapter {adapter!r} for port {port}",
            )
    return resolved


def resolve_provider_catalogs(
    container: Any,
    *,
    capabilities: set[str],
    authenticator: CredentialAuthenticator,
    identity_queries: IdentityQueries,
    authorize: AuthorizeService,
    content_queries: ContentQueries | None,
    session_revoker: OidcSessionRevoker | None,
    settings_queries: Any,
) -> dict[str, ProviderCatalog[Any]]:
    """Construct and freeze all provider implementations allowed by a manifest.

    Ordinary Port bindings still use :func:`resolve_adapters`.  This helper is
    for provider-valued Ports only: every implementation whose dependency
    capabilities are enabled is instantiated once at boot and exposed via a
    catalog.  Provider SDKs remain lazy/inert until their Port method is
    called, so registering a provider never opens a network connection.
    """

    catalogs: dict[str, ProviderCatalog[Any]] = {}
    for port, adapter_keys in PROVIDER_ADAPTERS.items():
        owner, provider_capabilities = PORT_CONTRACTS[port]
        if owner not in capabilities or not set(provider_capabilities) <= capabilities:
            continue
        catalog: ProviderCatalog[Any] = ProviderCatalog(port)
        for adapter_key in adapter_keys:
            requirements = set(ADAPTER_REQUIREMENTS.get(adapter_key, ()))
            if not requirements <= capabilities:
                continue
            bound = resolve_adapters(
                container,
                bindings=((port, adapter_key),),
                authenticator=authenticator,
                identity_queries=identity_queries,
                authorize=authorize,
                content_queries=content_queries,
                session_revoker=session_revoker,
                settings_queries=settings_queries,
            ).get(port)
            # notification.email historically exposes an ordered tuple Port;
            # a single synthetic binding still returns a one-item tuple.
            if isinstance(bound, tuple) and len(bound) == 1:
                bound = bound[0]
            if bound is None:
                continue
            # Provider keys are the provider Port's stable public key, not a
            # Python class name.  This preserves the keys already persisted
            # in payment/asset rows while allowing manifest adapter aliases
            # (for example ``payments.dev_fake``) during boot.
            catalog.register(str(getattr(bound, "key", adapter_key)), bound)
        catalog.freeze()
        catalogs[port] = catalog
    return catalogs
