"""Application container: registries, port resolution, lifecycle.

Contract source: context/spec/composition.md §5/§6, context/spec/kernel/boot.md.

``build_container`` constructs every registry and service for a manifest
without opening connections or starting tasks; ``freeze`` locks all
registries; ``start``/``stop`` manage the background workers. Missing
capabilities, unknown adapters, unbound required ports or duplicate keys
fail before anything can serve. The container imports capabilities only
through their package-root public surfaces.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass, field
from typing import Any

from inc.api.adapters import ContentBatchExists, InMemoryObjectStorage, resolve_adapters
from inc.capabilities.access import (
    AccessDiagnostics,
    AccessQueries,
    AuthorizeService,
    PermissionRegistry,
)
from inc.capabilities.assets import (
    AssetDiagnostics,
    AssetQueries,
    register_asset_workflows,
)
from inc.capabilities.assets import (
    CommandContext as AssetCommandContext,
)
from inc.capabilities.audit import AuditInboxHandler, AuditQueries
from inc.capabilities.content import (
    ContentDiagnostics,
    ContentPublishScanner,
    ContentQueries,
    ContentTypeRegistry,
    ScheduledPublishActivity,
    register_publish_workflow,
)
from inc.capabilities.identity import (
    CredentialAuthenticator,
    IdentityDiagnostics,
    IdentityQueries,
)
from inc.capabilities.oidc_provider import (
    AuthorizationService,
    InMemorySigningKeyStore,
    KeyService,
    LogoutService,
    OidcDiagnostics,
    OidcSessionRevoker,
    RevocationService,
    SecurityEventRevoker,
    ServiceContext,
    TokenService,
    UserInfoService,
)
from inc.capabilities.settings import (
    SettingGroupRegistry,
    SettingsQueries,
    build_seo_group_spec,
)
from inc.capabilities.taxonomy import (
    DimensionRegistry,
    TaxonomyDiagnostics,
    TaxonomyQueries,
)
from inc.kernel.boot import AppManifest, CapabilitySpec, FeatureSpec
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import (
    EventHandlerRegistry,
    EventSchemaRegistry,
    OutboxDispatcher,
    OutboxWriter,
)
from inc.kernel.observability import AdminSummaryRegistry, DiagnosticRegistry
from inc.kernel.security import Argon2PasswordHasher
from inc.kernel.time import Clock
from inc.kernel.workflow import WorkflowRegistry, WorkflowRunner

CAPABILITY_SPECS: dict[str, CapabilitySpec] = {}
FEATURE_SPECS: dict[str, FeatureSpec] = {}

for _module, _attr in (
    ("inc.capabilities.identity.definition", "spec"),
    ("inc.capabilities.access.definition", "spec"),
    ("inc.capabilities.oidc_provider.definition", "spec"),
    ("inc.capabilities.audit.definition", "spec"),
    ("inc.capabilities.settings.definition", "spec"),
    ("inc.capabilities.content.definition", "spec"),
    ("inc.capabilities.taxonomy.definition", "spec"),
    ("inc.capabilities.assets.definition", "spec"),
):
    _spec = getattr(importlib.import_module(_module), _attr)
    CAPABILITY_SPECS[_module.rsplit(".", 2)[1]] = _spec

for _module, _attr in (
    ("inc.features.post.definition", "spec"),
    ("inc.features.page.definition", "spec"),
):
    _spec = getattr(importlib.import_module(_module), _attr)
    FEATURE_SPECS[_module.rsplit(".", 2)[1]] = _spec

REQUIRED_PORTS: dict[str, tuple[str, ...]] = {
    "oidc_provider": (
        "oidc.subject_authenticator",
        "oidc.subject_claims",
        "oidc.authorization_decision",
        "oidc.security_events",
    ),
    "taxonomy": ("taxonomy.target_exists",),
    "assets": ("assets.object_storage",),
}

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"
SECURITY_EVENT_KEYS = ("identity.user_banned.v1", "identity.password_changed.v1")


def _fail(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.INTERNAL, message=message)


@dataclass(slots=True)
class Services:
    """Aggregated service objects handed to routers and workers."""

    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    dispatcher: OutboxDispatcher
    runner: WorkflowRunner
    identity_queries: IdentityQueries
    access_queries: AccessQueries
    authorize: AuthorizeService
    keys: KeyService
    hasher: Argon2PasswordHasher
    permission_registry: PermissionRegistry
    content_types: ContentTypeRegistry
    dimensions: DimensionRegistry
    settings_groups: SettingGroupRegistry
    content_queries: ContentQueries
    taxonomy_queries: TaxonomyQueries
    settings_queries: SettingsQueries
    audit_queries: AuditQueries
    adapters: dict[str, Any] = field(default_factory=dict)
    settings: Any = None
    asset_queries: AssetQueries | None = None
    scanner: ContentPublishScanner | None = None
    oidc: dict[str, Any] | None = None
    dev_storage: Any = None


class ApplicationContainer:
    """One manifest's full runtime wiring; frozen before serving."""

    def __init__(
        self,
        *,
        manifest: AppManifest,
        uow_factory: UoWFactory,
        clock: Clock,
        settings: Any,
    ) -> None:
        self._manifest = manifest
        self._uow_factory = uow_factory
        self._clock = clock
        self._settings = settings
        self._frozen = False
        self._tasks: list[asyncio.Task[Any]] = []
        self.schema_registry = EventSchemaRegistry()
        self.handler_registry = EventHandlerRegistry()
        self.workflow_registry = WorkflowRegistry()
        self.permission_registry = PermissionRegistry()
        self.content_types = ContentTypeRegistry(permission_keys=self.permission_registry)
        self.dimensions = DimensionRegistry(permission_keys=self.permission_registry)
        self.settings_groups = SettingGroupRegistry()
        self.diagnostic_registry = DiagnosticRegistry()
        self.admin_summary_registry = AdminSummaryRegistry()
        self.services: Services | None = None

    # -- construction -----------------------------------------------------

    def _require(self, key: str) -> None:
        if self._frozen:
            raise _fail("kernel.registry_frozen", f"container is frozen; cannot modify {key}")

    def _validate_manifest(self) -> None:
        for name in self._manifest.capabilities:
            if name not in CAPABILITY_SPECS:
                raise _fail("kernel.capability_unknown", f"capability {name!r} is not registered")
        for name in self._manifest.features:
            if name not in FEATURE_SPECS:
                raise _fail("kernel.feature_unknown", f"feature {name!r} is not registered")
            for required in FEATURE_SPECS[name].requires:
                if required not in self._manifest.capabilities:
                    raise _fail(
                        "kernel.feature_requires_missing",
                        f"feature {name!r} requires capability {required!r}",
                    )

    def _register_event_schemas(self) -> None:
        capabilities = set(self._manifest.capabilities)
        if "identity" in capabilities:
            from inc.capabilities.identity.events import IDENTITY_EVENT_SCHEMAS

            for key, schema in IDENTITY_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "content" in capabilities:
            from inc.capabilities.content.events import CONTENT_EVENT_SCHEMAS

            for key, schema in CONTENT_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "taxonomy" in capabilities:
            from inc.capabilities.taxonomy.events import TAXONOMY_EVENT_SCHEMAS

            for key, schema in TAXONOMY_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "settings" in capabilities:
            from inc.capabilities.settings.events import SETTINGS_EVENT_SCHEMAS

            for key, schema in SETTINGS_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        from inc.capabilities.audit.schemas import AuditEntryRecorded

        self.schema_registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)

    def _register_permissions(self) -> None:
        for name in self._manifest.capabilities:
            spec = CAPABILITY_SPECS[name]
            self.permission_registry.register_declared(name, spec.access_keys)

    def _register_declarations(self) -> None:
        for name in self._manifest.features:
            module = importlib.import_module(f"inc.features.{name}.definition")
            content_type = getattr(module, "content_type_spec", None)
            if content_type is not None:
                self.content_types.register(content_type)
            for dimension in getattr(module, "dimension_specs", ()):
                self.dimensions.register(dimension)
        if "settings" in self._manifest.capabilities:
            self.settings_groups.register(build_seo_group_spec())

    def _build_services(self) -> Services:
        capabilities = set(self._manifest.capabilities)
        outbox = OutboxWriter(self.schema_registry, self._clock)
        self._outbox = outbox
        hasher = Argon2PasswordHasher()
        identity_queries = IdentityQueries(uow_factory=self._uow_factory)
        authorize = AuthorizeService(uow_factory=self._uow_factory, clock=self._clock)
        access_queries = AccessQueries(uow_factory=self._uow_factory)
        content_queries = ContentQueries(uow_factory=self._uow_factory, types=self.content_types)
        taxonomy_queries = TaxonomyQueries(
            uow_factory=self._uow_factory, dimensions=self.dimensions
        )
        settings_queries = SettingsQueries(
            uow_factory=self._uow_factory, groups=self.settings_groups
        )
        audit_queries = AuditQueries(uow_factory=self._uow_factory)
        runner = WorkflowRunner(
            uow_factory=self._uow_factory, registry=self.workflow_registry, clock=self._clock
        )

        dev_storage: Any = None
        asset_queries: AssetQueries | None = None
        asset_command_ctx: AssetCommandContext | None = None
        if "assets" in capabilities:
            dev_storage = InMemoryObjectStorage()
            asset_command_ctx = AssetCommandContext(
                uow_factory=self._uow_factory,
                clock=self._clock,
                outbox=outbox,
                providers={"dev_memory": dev_storage},
                runner=runner,
            )
            register_asset_workflows(self.workflow_registry, ctx=asset_command_ctx)
            asset_queries = AssetQueries(ctx=asset_command_ctx, clock=self._clock)

        scanner: ContentPublishScanner | None = None
        if "content" in capabilities:
            publish_activity = ScheduledPublishActivity(
                clock=self._clock, outbox=outbox, actor_id="system"
            )
            register_publish_workflow(self.workflow_registry, activity=publish_activity)
            scanner = ContentPublishScanner(
                uow_factory=self._uow_factory, clock=self._clock, runner=runner
            )

        session_revoker = (
            OidcSessionRevoker(uow_factory=self._uow_factory, clock=self._clock)
            if "oidc_provider" in capabilities
            else None
        )
        adapters = resolve_adapters(
            self,
            bindings=self._manifest.adapters,
            authenticator=CredentialAuthenticator(uow_factory=self._uow_factory, hasher=hasher),
            identity_queries=identity_queries,
            authorize=authorize,
            content_queries=content_queries,
            session_revoker=session_revoker,
            dev_storage=dev_storage,
        )
        self._validate_required_ports(adapters)

        keys = KeyService(
            uow_factory=self._uow_factory,
            store=InMemorySigningKeyStore(),
            clock=self._clock,
        )
        oidc: dict[str, Any] | None = None
        if "oidc_provider" in capabilities:
            service_ctx = ServiceContext(
                uow_factory=self._uow_factory,
                clock=self._clock,
                outbox=outbox,
                keys=keys,
                authenticator=adapters["oidc.subject_authenticator"],
                claims_reader=adapters["oidc.subject_claims"],
                authorization_reader=adapters["oidc.authorization_decision"],
                issuer=getattr(self._settings, "issuer", "http://localhost:8080"),
            )
            oidc = {
                "authorization": AuthorizationService(service_ctx),
                "token": TokenService(service_ctx),
                "userinfo": UserInfoService(service_ctx),
                "revocation": RevocationService(service_ctx),
                "logout": LogoutService(service_ctx),
                "keys": keys,
                "ctx": service_ctx,
            }
            for event_key in SECURITY_EVENT_KEYS:
                self.handler_registry.register(
                    event_key,
                    SecurityEventRevoker(
                        subscriber=adapters["oidc.security_events"], clock=self._clock
                    ),
                )

        if "audit" in capabilities:
            self.handler_registry.register(AUDIT_EVENT_KEY, AuditInboxHandler(clock=self._clock))

        dispatcher = OutboxDispatcher(
            uow_factory=self._uow_factory,
            schema_registry=self.schema_registry,
            handler_registry=self.handler_registry,
            clock=self._clock,
        )

        if "identity" in capabilities:
            self.diagnostic_registry.register(
                IdentityDiagnostics(uow_factory=self._uow_factory, clock=self._clock)
            )
        if "access" in capabilities:
            self.diagnostic_registry.register(
                AccessDiagnostics(
                    uow_factory=self._uow_factory,
                    permissions=self.permission_registry,
                    clock=self._clock,
                )
            )
        if "oidc_provider" in capabilities:
            self.diagnostic_registry.register(
                OidcDiagnostics(uow_factory=self._uow_factory, clock=self._clock)
            )
        if "content" in capabilities:
            self.diagnostic_registry.register(
                ContentDiagnostics(
                    uow_factory=self._uow_factory, types=self.content_types, clock=self._clock
                )
            )
        if "taxonomy" in capabilities:
            self.diagnostic_registry.register(
                TaxonomyDiagnostics(
                    uow_factory=self._uow_factory,
                    batch_target_exists=ContentBatchExists(queries=content_queries),
                )
            )
        if "assets" in capabilities:
            self.diagnostic_registry.register(
                AssetDiagnostics(
                    uow_factory=self._uow_factory,
                    clock=self._clock,
                    providers={"dev_memory": dev_storage} if dev_storage is not None else {},
                )
            )

        self.services = Services(
            uow_factory=self._uow_factory,
            clock=self._clock,
            outbox=outbox,
            dispatcher=dispatcher,
            runner=runner,
            identity_queries=identity_queries,
            access_queries=access_queries,
            authorize=authorize,
            keys=keys,
            hasher=hasher,
            permission_registry=self.permission_registry,
            content_types=self.content_types,
            dimensions=self.dimensions,
            settings_groups=self.settings_groups,
            adapters=adapters,
            settings=self._settings,
            content_queries=content_queries,
            taxonomy_queries=taxonomy_queries,
            settings_queries=settings_queries,
            asset_queries=asset_queries,
            audit_queries=audit_queries,
            scanner=scanner,
            oidc=oidc,
            dev_storage=dev_storage,
        )
        return self.services

    def _validate_required_ports(self, adapters: dict[str, Any]) -> None:
        for capability in self._manifest.capabilities:
            for port in REQUIRED_PORTS.get(capability, ()):
                if port not in adapters:
                    raise _fail(
                        "kernel.port_unbound",
                        f"capability {capability!r} requires port {port!r} which is not bound",
                    )

    def build(self) -> ApplicationContainer:
        """Run the full boot sequence; callers must then freeze()."""

        self._require("build")
        self._validate_manifest()
        self._register_event_schemas()
        self._register_permissions()
        self._register_declarations()
        self._build_services()
        return self

    def freeze(self) -> None:
        for registry in (
            self.schema_registry,
            self.handler_registry,
            self.workflow_registry,
            self.permission_registry,
            self.content_types,
            self.dimensions,
            self.settings_groups,
            self.diagnostic_registry,
            self.admin_summary_registry,
        ):
            freeze_fn = getattr(registry, "freeze", None)
            if freeze_fn is not None:
                freeze_fn()
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        services = self.services
        if services is None:
            raise _fail("kernel.container_not_built", "container has not been built")
        sleep = getattr(self._settings, "worker_sleep_seconds", 1.0)
        if "outbox" in self._manifest.workers:
            self._tasks.append(
                asyncio.create_task(self._loop("outbox", services.dispatcher.dispatch_cycle, sleep))
            )
        if "workflow" in self._manifest.workers:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(
                        "workflow",
                        lambda: services.runner.run_due(batch=16),
                        sleep,
                    )
                )
            )
        if self._manifest.cron_enabled and services.scanner is not None:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(
                        "content-publish-scan",
                        services.scanner.scan_once,
                        max(sleep, 5.0),
                    )
                )
            )

    async def _loop(self, name: str, call: Any, sleep_seconds: float) -> None:
        while True:
            try:
                await call()
            except Exception:  # noqa: BLE001 - worker loops must survive individual failures
                pass
            await asyncio.sleep(sleep_seconds)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except Exception:  # noqa: BLE001
                pass
        self._tasks.clear()


def build_container(
    *,
    manifest: AppManifest,
    uow_factory: UoWFactory,
    clock: Clock,
    settings: Any,
) -> ApplicationContainer:
    container = ApplicationContainer(
        manifest=manifest, uow_factory=uow_factory, clock=clock, settings=settings
    )
    container.build()
    container.freeze()
    return container
