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
from typing import Any, cast

from inc.adapters import (
    ContentBatchExists,
    ProviderCatalog,
    ProviderResolver,
    resolve_adapters,
    resolve_provider_catalogs,
)
from inc.adapters.content.markdown_assets import ReadyMarkdownAssetsPolicy
from inc.adapters.registry import (
    ADAPTER_REQUIREMENTS,
    KNOWN_ADAPTERS,
    MULTI_PROVIDER_PORTS,
    PORT_CONTRACTS,
)
from inc.api.config import DEFAULT_ISSUER
from inc.api.retention import ManagementRetentionActivity
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
from inc.capabilities.audit import AuditInboxHandler, AuditQueries, AuditRetentionActivity
from inc.capabilities.comments import CommentQueries
from inc.capabilities.community import (
    GENERAL_DISCUSSION_TEMPLATE,
    CommunityDiagnostics,
    CommunityQueries,
    DiscussionTemplateRegistry,
)
from inc.capabilities.content import (
    ContentDiagnostics,
    ContentPublicationPolicy,
    ContentPublishScanner,
    ContentQueries,
    ContentTypeRegistry,
    ScheduledPublishActivity,
    register_publish_workflow,
)
from inc.capabilities.engagement import EngagementCommands, EngagementQueries
from inc.capabilities.engagement.ports import ContentEngagementTarget
from inc.capabilities.identity import (
    CredentialAuthenticator,
    IdentityDiagnostics,
    IdentityQueries,
)
from inc.capabilities.membership import (
    CommandContext as MembershipCommandContext,
)
from inc.capabilities.membership import (
    ExpireSubscription,
    MembershipAdminService,
    MembershipDiagnostics,
    MembershipLevelRegistry,
    MembershipLevelSpec,
    MembershipQueries,
)
from inc.capabilities.notification import (
    AUTH_NOTIFICATION_SPECS,
    AuthChallengeNotifier,
    DeliverActivity,
    NotificationDiagnostics,
    NotificationQueries,
    NotificationRetentionActivity,
    NotificationSpecRegistry,
    build_deliver_workflow_spec,
)
from inc.capabilities.notification import (
    CommandContext as NotificationCommandContext,
)
from inc.capabilities.notification.ports import NotificationProvider, ProviderChainResolver
from inc.capabilities.oidc_provider import (
    AuthorizationService,
    ClientQueries,
    GrantConsentService,
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
from inc.capabilities.payments import (
    PaymentsDiagnostics,
    PaymentsQueries,
)
from inc.capabilities.points import (
    CommandContext as PointsCommandContext,
)
from inc.capabilities.points import (
    ExpireBuckets,
    PointBehaviorRegistry,
    PointsAdminService,
    PointsDiagnostics,
    PointsQueries,
)
from inc.capabilities.settings import (
    SettingGroupRegistry,
    SettingsQueries,
)
from inc.capabilities.taxonomy import (
    DimensionRegistry,
    TaxonomyDiagnostics,
    TaxonomyQueries,
)
from inc.features.auth.api import AuthService
from inc.kernel.boot import AppManifest, CapabilitySpec, FeatureSpec
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import (
    EventHandlerRegistry,
    EventSchemaRegistry,
    OutboxDispatcher,
    OutboxWriter,
)
from inc.kernel.observability import AdminSummaryRegistry, DiagnosticRegistry, MetricRegistry
from inc.kernel.security import Argon2PasswordHasher, SensitiveValueProtector
from inc.kernel.tasks import (
    CronRegistry,
    CronScheduler,
    CronSpec,
    ExecutionLogCleaner,
    ExecutionLogQueries,
    TaskRegistry,
    TaskSpec,
    TaskWorker,
)
from inc.kernel.time import Clock
from inc.kernel.workflow import WorkflowRegistry, WorkflowRunner

CAPABILITY_DEFINITIONS: dict[str, tuple[str, str]] = {
    "identity": ("inc.capabilities.identity.definition", "spec"),
    "access": ("inc.capabilities.access.definition", "spec"),
    "oidc_provider": ("inc.capabilities.oidc_provider.definition", "spec"),
    "audit": ("inc.capabilities.audit.definition", "spec"),
    "settings": ("inc.capabilities.settings.definition", "spec"),
    "content": ("inc.capabilities.content.definition", "spec"),
    "comments": ("inc.capabilities.comments.definition", "spec"),
    "community": ("inc.capabilities.community.definition", "spec"),
    "taxonomy": ("inc.capabilities.taxonomy.definition", "spec"),
    "assets": ("inc.capabilities.assets.definition", "spec"),
    "notification": ("inc.capabilities.notification.definition", "spec"),
    "points": ("inc.capabilities.points.definition", "spec"),
    "payments": ("inc.capabilities.payments.definition", "spec"),
    "membership": ("inc.capabilities.membership.definition", "spec"),
    "engagement": ("inc.capabilities.engagement.definition", "spec"),
}

STAT_PROVIDER_MODULES: dict[str, str] = {
    "identity": "inc.capabilities.identity.stat",
    "access": "inc.capabilities.access.stat",
    "oidc_provider": "inc.capabilities.oidc_provider.stat",
    "audit": "inc.capabilities.audit.stat",
    "settings": "inc.capabilities.settings.stat",
    "content": "inc.capabilities.content.stat",
    "comments": "inc.capabilities.comments.stat",
    "community": "inc.capabilities.community.stat",
    "taxonomy": "inc.capabilities.taxonomy.stat",
    "assets": "inc.capabilities.assets.stat",
    "notification": "inc.capabilities.notification.stat",
    "points": "inc.capabilities.points.stat",
    "payments": "inc.capabilities.payments.stat",
    "membership": "inc.capabilities.membership.stat",
    "engagement": "inc.capabilities.engagement.stat",
}

FEATURE_DEFINITIONS: dict[str, tuple[str, str]] = {
    "post": ("inc.features.post.definition", "spec"),
    "page": ("inc.features.page.definition", "spec"),
    "site_settings": ("inc.features.site_settings.definition", "spec"),
    "check_in": ("inc.features.check_in.definition", "spec"),
    "auth": ("inc.features.auth.definition", "spec"),
    "membership_grants": ("inc.features.membership_grants.definition", "spec"),
    "site_cleanup": ("inc.features.site_cleanup.definition", "spec"),
    "content_engagement": ("inc.features.content_engagement.definition", "spec"),
    "content_bucket": ("inc.features.content_bucket.definition", "spec"),
}

REQUIRED_PORTS: dict[str, tuple[str, ...]] = {
    capability: tuple(
        port for port, (owner, _providers) in PORT_CONTRACTS.items() if owner == capability
    )
    for capability in {owner for owner, _providers in PORT_CONTRACTS.values()}
}

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"
SECURITY_EVENT_KEYS = ("identity.user_banned.v1", "identity.password_changed.v1")


@dataclass(frozen=True, slots=True)
class RouterBinding:
    """Lazy router module binding and its manifest requirements."""

    module: str | None
    capabilities: tuple[str, ...] = ()
    features: tuple[str, ...] = ()


class _ContentEngagementReader:
    """Composition adapter from content DTOs to the engagement port."""

    def __init__(self, queries: ContentQueries) -> None:
        self._queries = queries

    async def get(self, content_id: Any) -> ContentEngagementTarget | None:
        content = await self._queries.get(content_id)
        if content is None:
            return None
        return ContentEngagementTarget(
            content_id=content_id,
            type_name=content.type_name,
            status=content.status,
            published_at=content.published_at,
        )


ROUTER_BINDINGS: dict[str, RouterBinding] = {
    "health": RouterBinding(module=None),
    "auth": RouterBinding(
        module="inc.api.http.routers_auth",
        capabilities=("identity", "oidc_provider"),
        features=("auth",),
    ),
    "me": RouterBinding(
        module="inc.api.http.routers_me",
        capabilities=("identity", "assets", "settings", "points"),
        features=("check_in",),
    ),
    "admin_session": RouterBinding(
        module="inc.api.http.routers_admin_session", capabilities=("identity", "access")
    ),
    "identity": RouterBinding(module="inc.api.http.routers_identity", capabilities=("identity",)),
    "access": RouterBinding(module="inc.api.http.routers_access", capabilities=("access",)),
    "content": RouterBinding(module="inc.api.http.routers_content", capabilities=("content",)),
    "comments": RouterBinding(module="inc.api.http.routers_comments", capabilities=("comments",)),
    "comments_admin": RouterBinding(
        module="inc.api.http.routers_comments_admin", capabilities=("comments",)
    ),
    "community": RouterBinding(
        module="inc.api.http.routers_community", capabilities=("community",)
    ),
    "community_admin": RouterBinding(
        module="inc.api.http.routers_community_admin", capabilities=("community",)
    ),
    "content_public": RouterBinding(
        module="inc.api.http.routers_content_public",
        capabilities=("content", "engagement"),
        features=("content_engagement",),
    ),
    "engagement": RouterBinding(
        module="inc.api.http.routers_engagement",
        capabilities=("engagement",),
        features=("content_engagement",),
    ),
    "dashboard": RouterBinding(module="inc.api.http.routers_dashboard", capabilities=("access",)),
    "taxonomy": RouterBinding(module="inc.api.http.routers_taxonomy", capabilities=("taxonomy",)),
    "settings": RouterBinding(module="inc.api.http.routers_settings", capabilities=("settings",)),
    "assets": RouterBinding(module="inc.api.http.routers_assets", capabilities=("assets",)),
    "content_bucket": RouterBinding(
        module="inc.api.http.routers_content_bucket",
        capabilities=("assets", "settings"),
        features=("content_bucket",),
    ),
    "audit": RouterBinding(module="inc.api.http.routers_audit", capabilities=("audit",)),
    "execution": RouterBinding(module="inc.api.http.routers_execution", capabilities=("audit",)),
    "oidc": RouterBinding(
        module=None,
        capabilities=("oidc_provider", "identity", "access", "audit"),
    ),
    "check_in": RouterBinding(
        module="inc.api.http.routers_check_in",
        capabilities=("points",),
        features=("check_in",),
    ),
    "points": RouterBinding(module="inc.api.http.routers_points", capabilities=("points",)),
    "points_admin": RouterBinding(
        module="inc.api.http.routers_points_admin", capabilities=("points",)
    ),
    "membership_admin": RouterBinding(
        module="inc.api.http.routers_membership_admin", capabilities=("membership",)
    ),
    "oidc_admin": RouterBinding(
        module="inc.api.http.routers_oidc_admin", capabilities=("oidc_provider",)
    ),
    "notifications_admin": RouterBinding(
        module="inc.api.http.routers_notifications_admin", capabilities=("notification",)
    ),
}
KNOWN_ROUTERS = frozenset(ROUTER_BINDINGS)
KNOWN_WORKERS = frozenset({"outbox", "workflow", "task"})


def _fail(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.INTERNAL, message=message)


def _task_handler(call: Any) -> Any:
    """Adapt a no-argument maintenance call to the kernel TaskHandler shape."""

    async def handler(uow: Any, data: dict[str, Any], context: Any) -> dict[str, Any]:
        del uow, data, context
        result = await call()
        if isinstance(result, dict):
            return dict(result)
        if isinstance(result, (list, tuple, set)):
            return {"processed": len(result)}
        if isinstance(result, int):
            return {"processed": result}
        return {"processed": 1}

    return handler


@dataclass(slots=True)
class Services:
    """Aggregated service objects handed to routers and workers."""

    uow_factory: UoWFactory
    clock: Clock
    metrics: MetricRegistry
    outbox: OutboxWriter
    dispatcher: OutboxDispatcher
    runner: WorkflowRunner
    identity_queries: IdentityQueries
    access_queries: AccessQueries
    authorize: AuthorizeService
    keys: KeyService | None
    hasher: Argon2PasswordHasher
    permission_registry: PermissionRegistry
    content_types: ContentTypeRegistry
    community_templates: DiscussionTemplateRegistry
    dimensions: DimensionRegistry
    settings_groups: SettingGroupRegistry
    content_queries: ContentQueries
    comments_queries: CommentQueries | None
    community_queries: CommunityQueries | None
    taxonomy_queries: TaxonomyQueries
    settings_queries: SettingsQueries
    audit_queries: AuditQueries
    execution_queries: ExecutionLogQueries
    behaviors: PointBehaviorRegistry
    points_queries: PointsQueries
    payments_queries: PaymentsQueries
    points_admin: PointsAdminService | None = None
    membership_levels: MembershipLevelRegistry | None = None
    membership_admin: MembershipAdminService | None = None
    membership_queries: MembershipQueries | None = None
    me: Any | None = None
    auth: AuthService | None = None
    adapters: dict[str, Any] = field(default_factory=dict)
    settings: Any = None
    asset_providers: dict[str, Any] = field(default_factory=dict)
    asset_queries: AssetQueries | None = None
    content_publication_policies: dict[str, ContentPublicationPolicy] = field(default_factory=dict)
    scanner: ContentPublishScanner | None = None
    oidc: dict[str, Any] | None = None
    oidc_grants: GrantConsentService | None = None
    oidc_client_queries: ClientQueries | None = None
    payment_providers: dict[str, Any] = field(default_factory=dict)
    engagement_commands: EngagementCommands | None = None
    engagement_queries: EngagementQueries | None = None
    community_diagnostics: CommunityDiagnostics | None = None
    notification_queries: NotificationQueries | None = None
    notification_specs: NotificationSpecRegistry | None = None
    notification_resolver: Any | None = None
    notification_providers: dict[str, tuple[NotificationProvider, ...] | ProviderChainResolver] = (
        field(default_factory=dict)
    )
    provider_catalogs: dict[str, ProviderCatalog[Any]] = field(default_factory=dict)
    provider_resolvers: dict[str, ProviderResolver[Any]] = field(default_factory=dict)
    notification_auth: AuthChallengeNotifier | None = None
    admin_summaries: AdminSummaryRegistry | None = None
    task_worker: TaskWorker | None = None
    cron_scheduler: CronScheduler | None = None
    admin_session_store: Any | None = None

    async def selected_provider_key(self, port: str) -> str:
        """Return the provider selected by current persisted settings."""

        resolver = self.provider_resolvers.get(port)
        if resolver is None:
            raise KernelError(
                code="kernel.provider_unbound",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message=f"no provider resolver is bound for {port!r}",
            )
        return await resolver.selected_key()


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
        self.metrics = MetricRegistry()
        self._settings = settings
        self._frozen = False
        self._started = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._points_expire: ExpireBuckets | None = None
        self.capability_specs: dict[str, CapabilitySpec] = {}
        self.feature_specs: dict[str, FeatureSpec] = {}
        self._feature_modules: dict[str, Any] = {}
        self.schema_registry = EventSchemaRegistry()
        self.handler_registry = EventHandlerRegistry()
        self.workflow_registry = WorkflowRegistry()
        self.task_registry = TaskRegistry()
        self.cron_registry = CronRegistry()
        self.permission_registry = PermissionRegistry()
        self.content_types = ContentTypeRegistry(permission_keys=self.permission_registry)
        self.community_templates = DiscussionTemplateRegistry(
            permission_keys=self.permission_registry
        )
        self.dimensions = DimensionRegistry(permission_keys=self.permission_registry)
        self.settings_groups = SettingGroupRegistry()
        self.behaviors = PointBehaviorRegistry()
        self.membership_levels = MembershipLevelRegistry()
        self.notification_specs = NotificationSpecRegistry()
        self.diagnostic_registry = DiagnosticRegistry()
        self.admin_summary_registry = AdminSummaryRegistry()
        self.services: Services | None = None

    # -- construction -----------------------------------------------------

    def _require(self, key: str) -> None:
        if self._frozen:
            raise _fail("kernel.registry_frozen", f"container is frozen; cannot modify {key}")

    def _validate_manifest(self) -> None:
        self.capability_specs.clear()
        self.feature_specs.clear()
        self._feature_modules.clear()
        for name in self._manifest.capabilities:
            definition = CAPABILITY_DEFINITIONS.get(name)
            if definition is None:
                raise _fail("kernel.capability_unknown", f"capability {name!r} is not registered")
            module_name, attribute = definition
            spec = getattr(importlib.import_module(module_name), attribute)
            self.capability_specs[name] = spec
            for required in spec.requires:
                if required not in self._manifest.capabilities:
                    raise _fail(
                        "kernel.capability_requires_missing",
                        f"capability {name!r} requires capability {required!r}",
                    )
        for name in self._manifest.features:
            definition = FEATURE_DEFINITIONS.get(name)
            if definition is None:
                raise _fail("kernel.feature_unknown", f"feature {name!r} is not registered")
            module_name, attribute = definition
            module = importlib.import_module(module_name)
            self._feature_modules[name] = module
            spec = getattr(module, attribute)
            self.feature_specs[name] = spec
            for required in spec.requires:
                if required not in self._manifest.capabilities:
                    raise _fail(
                        "kernel.feature_requires_missing",
                        f"feature {name!r} requires capability {required!r}",
                    )
        if (
            "site_cleanup" in self._manifest.features
            and "site_settings" not in self._manifest.features
        ):
            raise _fail(
                "kernel.feature_requires_missing",
                "feature 'site_cleanup' requires feature 'site_settings'",
            )
        for group_name, group, known in (
            ("capability", self._manifest.capabilities, set(CAPABILITY_DEFINITIONS)),
            ("feature", self._manifest.features, set(FEATURE_DEFINITIONS)),
            ("router", self._manifest.routers, KNOWN_ROUTERS),
            ("worker", self._manifest.workers, KNOWN_WORKERS),
        ):
            if len(set(group)) != len(group):
                raise _fail(
                    "kernel.manifest_duplicate",
                    f"manifest lists duplicate {group_name} entries",
                )
            unknown = set(group) - known
            if unknown:
                raise _fail(
                    "kernel.registry_unknown",
                    f"unknown {group_name} in manifest: {sorted(unknown)}",
                )
        capabilities = set(self._manifest.capabilities)
        features = set(self._manifest.features)
        for router_name in self._manifest.routers:
            binding = ROUTER_BINDINGS[router_name]
            missing_capabilities = set(binding.capabilities) - capabilities
            if missing_capabilities:
                raise _fail(
                    "kernel.router_requires_missing",
                    f"router {router_name!r} requires capabilities {sorted(missing_capabilities)}",
                )
            missing_features = set(binding.features) - features
            if missing_features:
                raise _fail(
                    "kernel.router_requires_missing",
                    f"router {router_name!r} requires features {sorted(missing_features)}",
                )
        if self._manifest.cron_enabled and "task" not in self._manifest.workers:
            raise _fail(
                "kernel.cron_worker_missing",
                "cron_enabled requires the task worker",
            )

    def _validate_adapter_bindings(self) -> None:
        """Validate port ownership and provider capabilities before resolution."""

        capabilities = set(self._manifest.capabilities)
        seen_ports: set[str] = set()
        for port, _adapter in self._manifest.adapters:
            if port in seen_ports and port not in MULTI_PROVIDER_PORTS:
                raise _fail(
                    "kernel.port_duplicate",
                    f"port {port} bound more than once",
                )
            seen_ports.add(port)
        seen_ports.clear()
        for port, adapter in self._manifest.adapters:
            if port in seen_ports and port not in MULTI_PROVIDER_PORTS:
                raise _fail(
                    "kernel.port_duplicate",
                    f"port {port} bound more than once",
                )
            seen_ports.add(port)
            if adapter not in KNOWN_ADAPTERS:
                raise _fail(
                    "kernel.adapter_unknown",
                    f"unknown adapter {adapter!r} for port {port!r}",
                )
            contract = PORT_CONTRACTS.get(port)
            if contract is None:
                raise _fail("kernel.port_unknown", f"unknown port {port!r}")
            owner, port_providers = contract
            if owner not in capabilities:
                raise _fail(
                    "kernel.port_owner_missing",
                    f"port {port!r} belongs to disabled capability {owner!r}",
                )
            adapter_providers = set(ADAPTER_REQUIREMENTS[adapter])
            required_providers = set(port_providers)
            missing = required_providers - capabilities
            if missing:
                raise _fail(
                    "kernel.adapter_dependency_missing",
                    f"port {port!r} requires provider capabilities {sorted(missing)}",
                )
            if not required_providers <= adapter_providers:
                raise _fail(
                    "kernel.adapter_contract_mismatch",
                    f"adapter {adapter!r} cannot provide port {port!r}",
                )

    def _register_cron(self, *, key: str, schedule: str, handler: Any) -> None:
        """Register one CronSpec and its persistent TaskInstance handler."""

        self.cron_registry.register(
            CronSpec(
                key=key,
                schedule=schedule,
                timezone="UTC",
                handler=handler,
            )
        )
        self.task_registry.register(TaskSpec(key=f"{key}.tick", handler=handler))

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
        if "comments" in capabilities:
            from inc.capabilities.comments.events import COMMENT_EVENT_SCHEMAS

            for key, schema in COMMENT_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "community" in capabilities:
            from inc.capabilities.community.events import COMMUNITY_EVENT_SCHEMAS

            for key, schema in COMMUNITY_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "taxonomy" in capabilities:
            from inc.capabilities.taxonomy.events import TAXONOMY_EVENT_SCHEMAS

            for key, schema in TAXONOMY_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "access" in capabilities:
            from inc.capabilities.access.events import ACCESS_EVENT_SCHEMAS

            for key, schema in ACCESS_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "settings" in capabilities:
            from inc.capabilities.settings.events import SETTINGS_EVENT_SCHEMAS

            for key, schema in SETTINGS_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "points" in capabilities:
            from inc.capabilities.points.events import POINTS_EVENT_SCHEMAS

            for key, schema in POINTS_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "payments" in capabilities:
            from inc.capabilities.payments.schemas import PAYMENT_EVENT_SCHEMAS

            for key, schema in PAYMENT_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "membership" in capabilities:
            from inc.capabilities.membership.events import MEMBERSHIP_EVENT_SCHEMAS

            for key, schema in MEMBERSHIP_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        if "notification" in capabilities:
            from inc.capabilities.notification.events import NOTIFICATION_EVENT_SCHEMAS

            for key, schema in NOTIFICATION_EVENT_SCHEMAS.items():
                self.schema_registry.register(key, schema)
        from inc.capabilities.audit.schemas import AuditEntryRecorded

        if "audit" in capabilities:
            self.schema_registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)

    def _register_permissions(self) -> None:
        for name in self._manifest.capabilities:
            spec = self.capability_specs[name]
            self.permission_registry.register_declared(name, spec.access_keys)
        if "access" in self._manifest.capabilities:
            self.permission_registry.register_alias("admin.dashboard.read", owner="access")

    def _register_declarations(self) -> None:
        capabilities = set(self._manifest.capabilities)
        for name in self._manifest.features:
            module = self._feature_modules[name]
            if "notification" in capabilities:
                for notification_spec in getattr(module, "notification_specs", ()):
                    self.notification_specs.register(notification_spec)
            content_type = getattr(module, "content_type_spec", None)
            if content_type is not None:
                self.content_types.register(content_type)
            for dimension in getattr(module, "dimension_specs", ()):
                self.dimensions.register(dimension)
            for behavior in getattr(module, "behavior_specs", ()):
                self.behaviors.register(behavior)
            for level in getattr(module, "level_specs", ()):
                self.membership_levels.register(level)
        if "notification" in capabilities:
            for notification_spec in AUTH_NOTIFICATION_SPECS:
                self.notification_specs.register(notification_spec)
        # The release composition owns a small, production-safe membership
        # catalog even though it deliberately does not enable the payment
        # purchase feature. Keep the declaration explicit and stable so
        # subscriptions can be granted by administrators without a purchase
        # workflow.
        if "membership" in self._manifest.capabilities and not self.membership_levels.specs():
            self.membership_levels.register(
                MembershipLevelSpec(
                    key="basic",
                    display_name="Basic",
                    tier_rank=1,
                    cycle_days=30,
                    grant_points=100,
                    renewal_allowed=True,
                )
            )
        # The release composition does not enable a payment-backed membership
        # purchase workflow, but subscriptions still need the stable grant
        # behavior consumed by the membership PointsLedger port. Keep this
        # explicit whether or not the standalone payments capability is
        # installed: a provider catalog is not a purchase workflow.
        if "membership" in self._manifest.capabilities:
            from inc.features.membership_grants.definition import behavior_specs

            for behavior in behavior_specs:
                if not any(item.key == behavior.key for item in self.behaviors.specs()):
                    self.behaviors.register(behavior)
        if "site_settings" in self._manifest.features:
            from inc.features.site_settings.definition import (
                build_site_setting_group_specs,
            )

            setting_specs = build_site_setting_group_specs()
            if "payments" not in capabilities:
                setting_specs = tuple(
                    spec for spec in setting_specs if spec.group_key != "payments"
                )
            for spec in setting_specs:
                self.settings_groups.register(spec)
        if "community" in self._manifest.capabilities:
            self.community_templates.register(GENERAL_DISCUSSION_TEMPLATE)

    def _build_services(self) -> Services:
        capabilities = set(self._manifest.capabilities)
        outbox = OutboxWriter(self.schema_registry, self._clock)
        self._outbox = outbox
        hasher = Argon2PasswordHasher()
        identity_queries = IdentityQueries(uow_factory=self._uow_factory)
        authorize = AuthorizeService(
            uow_factory=self._uow_factory,
            clock=self._clock,
            permissions=self.permission_registry,
        )
        access_queries = AccessQueries(uow_factory=self._uow_factory)
        content_queries = ContentQueries(uow_factory=self._uow_factory, types=self.content_types)
        comments_queries = (
            CommentQueries(uow_factory=self._uow_factory) if "comments" in capabilities else None
        )
        community_queries: CommunityQueries | None = None
        community_diagnostics: CommunityDiagnostics | None = None
        engagement_commands: EngagementCommands | None = None
        engagement_queries: EngagementQueries | None = None
        if "engagement" in capabilities:
            engagement_commands = EngagementCommands(
                uow_factory=self._uow_factory,
                clock=self._clock,
                content_reader=_ContentEngagementReader(content_queries),
            )
            engagement_queries = EngagementQueries(
                uow_factory=self._uow_factory,
                commands=engagement_commands,
            )
        taxonomy_queries = TaxonomyQueries(
            uow_factory=self._uow_factory, dimensions=self.dimensions
        )
        settings_queries = SettingsQueries(
            uow_factory=self._uow_factory, groups=self.settings_groups
        )
        audit_queries = AuditQueries(uow_factory=self._uow_factory)
        execution_queries = ExecutionLogQueries(uow_factory=self._uow_factory)
        execution_cleaner = ExecutionLogCleaner(self._uow_factory)
        runner = WorkflowRunner(
            uow_factory=self._uow_factory,
            registry=self.workflow_registry,
            clock=self._clock,
            metrics=self.metrics,
        )

        asset_queries: AssetQueries | None = None
        content_publication_policies: dict[str, ContentPublicationPolicy] = {}
        asset_command_ctx: AssetCommandContext | None = None

        scanner: ContentPublishScanner | None = None
        if "content" in capabilities:
            publish_activity = ScheduledPublishActivity(
                clock=self._clock,
                outbox=outbox,
                types=self.content_types,
                publication_policies=content_publication_policies,
                actor_id="system",
            )
            register_publish_workflow(self.workflow_registry, activity=publish_activity)
            scanner = ContentPublishScanner(
                uow_factory=self._uow_factory, clock=self._clock, runner=runner
            )
            self._register_cron(
                key="content.publish.scan.v1",
                schedule="* * * * *",
                handler=_task_handler(scanner.scan_once),
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
            settings_queries=settings_queries,
        )
        provider_catalogs = resolve_provider_catalogs(
            self,
            capabilities=capabilities,
            authenticator=CredentialAuthenticator(uow_factory=self._uow_factory, hasher=hasher),
            identity_queries=identity_queries,
            authorize=authorize,
            content_queries=content_queries,
            session_revoker=session_revoker,
            settings_queries=settings_queries,
        )
        provider_resolvers: dict[str, ProviderResolver[Any]] = {}
        for port, catalog in provider_catalogs.items():
            bound = next(
                (
                    provider
                    for bound_port, adapter_key in self._manifest.adapters
                    if bound_port == port
                    for provider in (
                        catalog.get(adapter_key) or catalog.get(adapter_key.split(".", 1)[-1]),
                    )
                    if provider is not None
                ),
                None,
            )
            default_key = getattr(bound, "key", None)
            if port == "notification.email":
                provider_resolvers[port] = ProviderResolver(
                    catalog=catalog,
                    settings_queries=settings_queries,
                    settings_group="notification",
                    settings_field="email_provider",
                    default_key=default_key,
                )
            elif port == "assets.object_storage":
                provider_resolvers[port] = ProviderResolver(
                    catalog=catalog,
                    settings_queries=settings_queries,
                    settings_group="object_storage",
                    settings_field="storage_provider",
                    default_key=default_key,
                )
            elif port == "payments.provider":
                provider_resolvers[port] = ProviderResolver(
                    catalog=catalog,
                    settings_queries=settings_queries,
                    settings_group="payments",
                    settings_field="provider",
                    default_key=default_key,
                )
        self._validate_required_ports(adapters)
        if "community" in capabilities:
            community_queries = CommunityQueries(
                uow_factory=self._uow_factory,
                templates=self.community_templates,
                author_port=adapters["community.author"],
            )
            community_diagnostics = CommunityDiagnostics(
                uow_factory=self._uow_factory,
                templates=self.community_templates,
                clock=self._clock,
                author_port=adapters["community.author"],
            )
            self.diagnostic_registry.register(community_diagnostics)

        notification_queries: NotificationQueries | None = None
        notification_resolver: Any | None = None
        notification_providers: dict[
            str, tuple[NotificationProvider, ...] | ProviderChainResolver
        ] = {}
        notification_auth: AuthChallengeNotifier | None = None
        if "notification" in capabilities:
            sensitive_value_protector = SensitiveValueProtector.from_secret(
                getattr(
                    self._settings,
                    "admin_session_secret",
                    "dev-admin-session-secret-change-me",
                )
            )
            notification_queries = NotificationQueries(uow_factory=self._uow_factory)
            notification_resolver = adapters["notification.recipient"]
            notification_resolver_for_email = provider_resolvers.get("notification.email")
            if notification_resolver_for_email is not None:
                notification_providers["email"] = cast(
                    ProviderChainResolver, notification_resolver_for_email
                )
            else:
                notification_providers["email"] = tuple(
                    cast(NotificationProvider, provider)
                    for provider in adapters["notification.email"]
                )
            notification_auth = AuthChallengeNotifier(
                NotificationCommandContext(
                    uow_factory=self._uow_factory,
                    clock=self._clock,
                    outbox=outbox,
                    specs=self.notification_specs,
                    resolver=notification_resolver,
                    providers=notification_providers,
                    runner=runner,
                    permissions=frozenset(self.permission_registry.keys()),
                    actor_id="system",
                    sensitive_value_protector=sensitive_value_protector,
                )
            )
            deliver_activity = DeliverActivity(
                clock=self._clock,
                outbox=outbox,
                specs=self.notification_specs,
                resolver=notification_resolver,
                providers=notification_providers,
                sensitive_value_protector=sensitive_value_protector,
                metrics=self.metrics,
            )
            self.workflow_registry.register(build_deliver_workflow_spec(activity=deliver_activity))
            self.diagnostic_registry.register(
                NotificationDiagnostics(
                    uow_factory=self._uow_factory,
                    specs=self.notification_specs,
                    clock=self._clock,
                )
            )

        auth_service: AuthService | None = None
        if "auth" in self._manifest.features:
            if notification_auth is None:
                raise _fail(
                    "kernel.feature_requires_missing",
                    "feature 'auth' requires the notification capability and its delivery port",
                )
            auth_service = AuthService(
                uow_factory=self._uow_factory,
                clock=self._clock,
                outbox=outbox,
                hasher=hasher,
                identity_queries=identity_queries,
                access_queries=access_queries,
                permission_registry=self.permission_registry,
                notification_auth=notification_auth,
            )

        asset_providers: dict[str, Any] = {}
        if "assets" in capabilities:
            asset_catalog = provider_catalogs.get("assets.object_storage")
            if asset_catalog is not None:
                asset_providers.update(
                    {
                        registration.key: registration.provider
                        for registration in asset_catalog.registrations()
                    }
                )
            else:
                asset_provider = adapters["assets.object_storage"]
                asset_providers[asset_provider.key] = asset_provider
            asset_command_ctx = AssetCommandContext(
                uow_factory=self._uow_factory,
                clock=self._clock,
                outbox=outbox,
                providers=asset_providers,
                runner=runner,
            )
            register_asset_workflows(self.workflow_registry, ctx=asset_command_ctx)
            asset_queries = AssetQueries(ctx=asset_command_ctx, clock=self._clock)
            content_publication_policies["assets.ready_markdown.v1"] = ReadyMarkdownAssetsPolicy(
                asset_queries
            )

        if "content" in capabilities:
            for content_type in self.content_types.specs():
                key = content_type.publication_policy_key
                if content_type.requires_ready_markdown_assets and (
                    key is None or key not in content_publication_policies
                ):
                    raise _fail(
                        "kernel.port_unbound",
                        "content publication policy "
                        f"{key!r} is not bound for {content_type.type_name}",
                    )

        payment_providers: dict[str, Any] = {}
        payment_catalog = provider_catalogs.get("payments.provider")
        if payment_catalog is not None:
            payment_providers.update(
                {
                    registration.key: registration.provider
                    for registration in payment_catalog.registrations()
                }
            )
        else:
            bound_provider = adapters.get("payments.provider")
            if bound_provider is not None:
                payment_providers[bound_provider.key] = bound_provider

        points_queries = PointsQueries(uow_factory=self._uow_factory, behaviors=self.behaviors)
        points_admin = (
            PointsAdminService(
                uow_factory=self._uow_factory,
                clock=self._clock,
                outbox=outbox,
                behaviors=self.behaviors,
            )
            if "points" in capabilities
            else None
        )
        payments_queries = PaymentsQueries(uow_factory=self._uow_factory)

        points_expire: ExpireBuckets | None = None
        if "points" in capabilities:
            points_expire = ExpireBuckets(
                PointsCommandContext(
                    uow_factory=self._uow_factory,
                    clock=self._clock,
                    outbox=outbox,
                    behaviors=self.behaviors,
                    actor_id="system",
                )
            )
            self._points_expire = points_expire
            self._register_cron(
                key="points.buckets.expire.v1",
                schedule="* * * * *",
                handler=_task_handler(points_expire),
            )

        features = set(self._manifest.features)
        me_service: Any | None = None
        if "check_in" in features:
            from inc.features.check_in.api import MeService

            me_service = MeService(
                uow_factory=self._uow_factory,
                clock=self._clock,
                outbox=outbox,
                hasher=hasher,
                runner=runner,
                identity_queries=identity_queries,
                points_queries=points_queries,
                behaviors=self.behaviors,
                settings_queries=settings_queries,
                asset_queries=asset_queries,
                asset_providers=asset_providers,
            )
        if "check_in" in features:
            from inc.features.check_in.workflows import (
                CheckInContext,
                build_check_in_workflow_spec,
            )

            points_ctx = PointsCommandContext(
                uow_factory=self._uow_factory,
                clock=self._clock,
                outbox=outbox,
                behaviors=self.behaviors,
                actor_id="feature:check_in",
            )
            self.workflow_registry.register(
                build_check_in_workflow_spec(
                    ctx=CheckInContext(points_ctx=points_ctx, clock=self._clock)
                )
            )
        membership_queries: MembershipQueries | None = None
        membership_ctx: MembershipCommandContext | None = None
        membership_admin: MembershipAdminService | None = None
        if "membership" in capabilities:
            membership_ctx = MembershipCommandContext(
                uow_factory=self._uow_factory,
                clock=self._clock,
                outbox=outbox,
                levels=self.membership_levels,
                subject_exists=adapters["membership.subject_exists"],
                points_ledger=adapters["membership.points_ledger"],
                permissions=frozenset(),
                actor_id="system",
                trace_id="membership",
            )
            membership_queries = MembershipQueries(
                uow_factory=self._uow_factory, levels=self.membership_levels
            )
            membership_admin = MembershipAdminService(
                uow_factory=self._uow_factory,
                clock=self._clock,
                outbox=outbox,
                levels=self.membership_levels,
            )
            self.diagnostic_registry.register(
                MembershipDiagnostics(
                    uow_factory=self._uow_factory,
                    levels=self.membership_levels,
                    clock=self._clock,
                )
            )
            self._register_cron(
                key="membership.subscription.expire.v1",
                schedule="* * * * *",
                handler=_task_handler(ExpireSubscription(membership_ctx)),
            )
        if "site_cleanup" in features:
            from inc.features.site_cleanup import SiteCleanupActivity
            from inc.features.site_cleanup.definition import RETENTION_CRON_KEY

            if "audit" not in capabilities:
                raise _fail(
                    "kernel.feature_requires_missing",
                    "feature 'site_cleanup' requires the audit capability",
                )
            cleanup_activity = SiteCleanupActivity(
                settings=settings_queries,
                execution_logs=execution_cleaner,
                audit=AuditRetentionActivity(
                    uow_factory=self._uow_factory,
                    outbox=outbox,
                    clock=self._clock,
                ),
                clock=self._clock,
            )
            self._register_cron(
                key=RETENTION_CRON_KEY,
                schedule="0 4 * * *",
                handler=cleanup_activity,
            )
        elif {"audit", "settings"}.issubset(capabilities):
            self._register_cron(
                key="management.retention.v1",
                schedule="0 4 * * *",
                handler=ManagementRetentionActivity(
                    settings=settings_queries,
                    execution_logs=execution_cleaner,
                    audit=AuditRetentionActivity(
                        uow_factory=self._uow_factory,
                        outbox=outbox,
                        clock=self._clock,
                    ),
                    clock=self._clock,
                ),
            )
        if "notification" in capabilities:
            self._register_cron(
                key="notification.retention.v1",
                schedule="15 4 * * *",
                handler=NotificationRetentionActivity(
                    settings=settings_queries,
                    clock=self._clock,
                ),
            )
        oidc: dict[str, Any] | None = None
        oidc_grants: GrantConsentService | None = None
        oidc_client_queries: ClientQueries | None = None
        keys: KeyService | None = None
        if "oidc_provider" in capabilities:
            keys = KeyService(
                uow_factory=self._uow_factory,
                store=adapters["oidc.signing_keys"],
                clock=self._clock,
            )
            service_ctx = ServiceContext(
                uow_factory=self._uow_factory,
                clock=self._clock,
                outbox=outbox,
                keys=keys,
                authenticator=adapters["oidc.subject_authenticator"],
                claims_reader=adapters["oidc.subject_claims"],
                authorization_reader=adapters["oidc.authorization_decision"],
                issuer=getattr(self._settings, "issuer", DEFAULT_ISSUER),
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
            oidc_grants = GrantConsentService(service_ctx)
            oidc_client_queries = ClientQueries(uow_factory=self._uow_factory)
            self._register_cron(
                key="oidc.keys.cleanup.v1",
                schedule="0 3 * * *",
                handler=_task_handler(keys.cleanup_expired_keys),
            )
            for event_key in SECURITY_EVENT_KEYS:
                self.handler_registry.register(
                    event_key,
                    SecurityEventRevoker(
                        subscriber=adapters["oidc.security_events"], clock=self._clock
                    ),
                )

        if "audit" in capabilities:
            self.handler_registry.register(AUDIT_EVENT_KEY, AuditInboxHandler(clock=self._clock))

        if "engagement" in capabilities and "content_engagement" in self._manifest.features:
            from inc.capabilities.content.events import CONTENT_EVENT_SCHEMAS
            from inc.capabilities.engagement.readmodels import ContentEngagementProjection

            projection = ContentEngagementProjection(
                uow_factory=self._uow_factory,
                clock=self._clock,
            )
            for event_key in CONTENT_EVENT_SCHEMAS:
                self.handler_registry.register(event_key, projection)

        dispatcher = OutboxDispatcher(
            uow_factory=self._uow_factory,
            schema_registry=self.schema_registry,
            handler_registry=self.handler_registry,
            clock=self._clock,
            metrics=self.metrics,
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
                    providers=asset_providers,
                )
            )
        if "points" in capabilities:
            self.diagnostic_registry.register(
                PointsDiagnostics(
                    uow_factory=self._uow_factory,
                    behaviors=self.behaviors,
                    clock=self._clock,
                )
            )
        if "payments" in capabilities:
            self.diagnostic_registry.register(
                PaymentsDiagnostics(uow_factory=self._uow_factory, clock=self._clock)
            )

        # Statistics are capability-owned and explicitly registered; the
        # dashboard only aggregates providers selected by this manifest.
        for capability in self._manifest.capabilities:
            module_name = STAT_PROVIDER_MODULES.get(capability)
            if module_name is None:
                continue
            module = importlib.import_module(module_name)
            provider_cls = module.Provider
            self.admin_summary_registry.register(
                provider_cls(uow_factory=self._uow_factory, clock=self._clock)
            )

        cron_scheduler = CronScheduler(
            uow_factory=self._uow_factory,
            registry=self.cron_registry,
            clock=self._clock,
        )
        task_worker = TaskWorker(
            uow_factory=self._uow_factory,
            registry=self.task_registry,
            clock=self._clock,
            metrics=self.metrics,
        )
        self.services = Services(
            uow_factory=self._uow_factory,
            clock=self._clock,
            metrics=self.metrics,
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
            community_templates=self.community_templates,
            dimensions=self.dimensions,
            settings_groups=self.settings_groups,
            adapters=adapters,
            settings=self._settings,
            asset_providers=asset_providers,
            content_queries=content_queries,
            comments_queries=comments_queries,
            taxonomy_queries=taxonomy_queries,
            engagement_commands=engagement_commands,
            engagement_queries=engagement_queries,
            notification_queries=notification_queries,
            notification_specs=self.notification_specs if "notification" in capabilities else None,
            notification_resolver=notification_resolver,
            notification_providers=notification_providers,
            provider_catalogs=provider_catalogs,
            provider_resolvers=provider_resolvers,
            notification_auth=notification_auth,
            admin_summaries=self.admin_summary_registry,
            settings_queries=settings_queries,
            asset_queries=asset_queries,
            content_publication_policies=content_publication_policies,
            audit_queries=audit_queries,
            execution_queries=execution_queries,
            behaviors=self.behaviors,
            points_queries=points_queries,
            payments_queries=payments_queries,
            points_admin=points_admin,
            community_queries=community_queries,
            community_diagnostics=community_diagnostics,
            membership_levels=self.membership_levels,
            membership_admin=membership_admin,
            membership_queries=membership_queries,
            me=me_service,
            auth=auth_service,
            scanner=scanner,
            oidc=oidc,
            oidc_grants=oidc_grants,
            oidc_client_queries=oidc_client_queries,
            payment_providers=payment_providers,
            task_worker=task_worker,
            cron_scheduler=cron_scheduler,
        )
        return self.services

    def _validate_required_ports(self, adapters: dict[str, Any]) -> None:
        for capability in self._manifest.capabilities:
            for port in REQUIRED_PORTS.get(capability, ()):
                if port not in adapters or adapters[port] is None:
                    raise _fail(
                        "kernel.port_unbound",
                        f"capability {capability!r} requires port {port!r} which is not bound",
                    )

    def _validate_handler_schemas(self) -> None:
        """Every registered handler must consume a registered event schema."""

        for event_key in self.handler_registry.keys():
            if self.schema_registry.schema_for(event_key) is None:
                raise _fail(
                    "kernel.handler_schema_missing",
                    f"handler for {event_key!r} has no registered event schema",
                )

    def build(self) -> ApplicationContainer:
        """Run the full boot sequence; callers must then freeze()."""

        self._require("build")
        self._validate_manifest()
        self._validate_adapter_bindings()
        self._register_event_schemas()
        self._register_permissions()
        self._register_declarations()
        self._build_services()
        self._validate_handler_schemas()
        return self

    def freeze(self) -> None:
        for registry in (
            self.schema_registry,
            self.handler_registry,
            self.workflow_registry,
            self.task_registry,
            self.cron_registry,
            self.permission_registry,
            self.content_types,
            self.community_templates,
            self.dimensions,
            self.settings_groups,
            self.behaviors,
            self.membership_levels,
            self.notification_specs,
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

    @property
    def manifest(self) -> AppManifest:
        """Return the immutable runtime declaration selected by the composition root."""

        return self._manifest

    @property
    def provider_catalogs(self) -> dict[str, ProviderCatalog[Any]]:
        """Expose boot-time provider catalogs from the composition root.

        The catalogs are built and frozen with the service graph.  Keeping this
        read-only access on the root makes the startup contract observable
        without requiring callers to reach through a concrete service object.
        """

        services = self.services
        if services is None:
            raise _fail("kernel.container_not_built", "container has not been built")
        return services.provider_catalogs

    @property
    def provider_resolvers(self) -> dict[str, ProviderResolver[Any]]:
        """Expose settings-backed provider resolvers from the composition root."""

        services = self.services
        if services is None:
            raise _fail("kernel.container_not_built", "container has not been built")
        return services.provider_resolvers

    async def selected_provider_key(self, port: str) -> str:
        """Resolve the currently selected provider for a registered port."""

        services = self.services
        if services is None:
            raise _fail("kernel.container_not_built", "container has not been built")
        return await services.selected_provider_key(port)

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        services = self.services
        if services is None:
            raise _fail("kernel.container_not_built", "container has not been built")
        if not self._frozen:
            raise _fail("kernel.container_not_frozen", "container must be frozen before start")
        if self._started:
            raise _fail("kernel.container_already_started", "container already started")
        if services.membership_admin is not None:
            await services.membership_admin.hydrate_persisted_levels()
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
        if "task" in self._manifest.workers and services.task_worker is not None:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(
                        "task",
                        lambda: services.task_worker.run_cycle(batch=16),
                        sleep,
                    )
                )
            )
        if self._manifest.cron_enabled and services.cron_scheduler is not None:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(
                        "cron",
                        services.cron_scheduler.tick,
                        max(sleep, 1.0),
                    )
                )
            )
        self._started = True

    async def _loop(self, name: str, call: Any, sleep_seconds: float) -> None:
        while True:
            try:
                await call()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - worker loops survive individual failures
                from inc.kernel.observability import get_logger  # noqa: PLC0415

                get_logger("api.workers").exception("worker %s cycle failed", name)
            await asyncio.sleep(sleep_seconds)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass
        self._tasks.clear()
        self._started = False


def build_container(
    *,
    manifest: AppManifest,
    uow_factory: UoWFactory,
    clock: Clock,
    settings: Any,
) -> ApplicationContainer:
    if getattr(settings, "environment", None) == "production" and manifest.name != "release":
        raise _fail(
            "kernel.production_manifest_denied",
            "production only supports the release manifest",
        )
    container = ApplicationContainer(
        manifest=manifest, uow_factory=uow_factory, clock=clock, settings=settings
    )
    container.build()
    container.freeze()
    return container
