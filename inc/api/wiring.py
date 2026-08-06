"""Explicit M1 application composition root wiring."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from inc.kernel.audit import AuditService, AuditUnitOfWork
from inc.kernel.auth import (
    AUTH_CODES,
    AUTH_EVENT_TYPES,
    AuthService,
    AuthUnitOfWork,
    PasswordResetMailContext,
)
from inc.kernel.cache import CACHE_CODES, Cache, build_cache
from inc.kernel.comment import (
    COMMENT_CODES,
    COMMENT_EVENT_TYPES,
    COMMENT_SLOT_KEYS,
    CommentService,
    CommentTargetPolicy,
    CommentUnitOfWork,
)
from inc.kernel.comment.wiring import register_pipelines as register_comment_pipelines
from inc.kernel.config import Settings
from inc.kernel.content import (
    CONTENT_CODES,
    CONTENT_EVENT_TYPES,
    CONTENT_SLOT_KEYS,
    ContentService,
    ContentTypeRegistry,
    ContentUnitOfWork,
)
from inc.kernel.content.wiring import register_pipelines as register_content_pipelines
from inc.kernel.db import DB_CODES, Database, UoWExecutor, create_database
from inc.kernel.errors import COMMON_CODES, ErrorCode, register_error_codes
from inc.kernel.events import EVENT_CODES, Event, EventBus, fresh_event_bus
from inc.kernel.identity import (
    IDENTITY_CODES,
    IDENTITY_EVENT_TYPES,
    IdentityService,
    IdentityUnitOfWork,
)
from inc.kernel.mail import (
    MAIL_CODES,
    MAIL_EVENT_TYPES,
    MailService,
    MailUnitOfWork,
    mail_template_registry,
    register_mail_template,
)
from inc.kernel.pipeline import PIPELINE_CODES, PipelineRegistry
from inc.kernel.rbac import (
    ALL_CAPABILITY_ALIASES,
    RBAC_CODES,
    RBAC_EVENT_TYPES,
    RBACService,
    RBACUnitOfWork,
    capability_registry,
    validate_capability_registry,
)
from inc.kernel.security import Principal, TokenService
from inc.kernel.settings import (
    SETTING_CODES,
    SETTING_EVENT_TYPES,
    SettingsService,
    SettingsUnitOfWork,
    SiteProfileSettings,
    register_setting,
    setting_registry,
)
from inc.kernel.tasks import TASK_CODES, TASK_EVENT_TYPES, TaskScheduler, TaskUnitOfWork
from inc.kernel.taxonomy import (
    TAXONOMY_EVENT_TYPES,
    TAXONOMY_SLOT_KEYS,
    TERM_CODES,
    TaxonomyUnitOfWork,
    TermService,
)
from inc.kernel.taxonomy.wiring import register_pipelines as register_taxonomy_pipelines
from inc.modules.forum.definition import ForumContentType
from inc.modules.interaction import (
    InteractionChangedPayload,
    InteractionService,
    InteractionUnitOfWork,
)
from inc.modules.issue.definition import IssueContentType
from inc.modules.post.definition import PostContentType

DECLARATIVE_CONTENT_TYPE_NAMES: tuple[str, ...] = ("post", "forum", "issue")


def _build_declarative_content_type_registry() -> ContentTypeRegistry:
    registry = ContentTypeRegistry()
    for declaration in (PostContentType, ForumContentType, IssueContentType):
        registry.register(declaration)
    if registry.keys() != DECLARATIVE_CONTENT_TYPE_NAMES:
        raise RuntimeError("declarative content type registration order is invalid")
    registry.freeze()
    return registry


declarative_content_type_registry = _build_declarative_content_type_registry()


def _comment_target_policy(type_name: str) -> CommentTargetPolicy | None:
    try:
        policy = declarative_content_type_registry.require(type_name).comment_policy
    except KeyError:
        return None
    return CommentTargetPolicy(
        allow=policy.allow,
        max_depth=policy.max_depth,
        auto_approve=policy.auto_approve,
        rate_limit=policy.rate_limit,
    )


_EXTENSION_SLOT_KEYS = (*CONTENT_SLOT_KEYS, *TAXONOMY_SLOT_KEYS, *COMMENT_SLOT_KEYS)


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    database: Database
    cache: Cache
    event_bus: EventBus
    token_service: TokenService
    identity: IdentityService
    rbac: RBACService
    auth: AuthService
    mail: MailService
    audit: AuditService
    runtime_settings: SettingsService
    scheduler: TaskScheduler
    content: ContentService
    taxonomy: TermService
    comments: CommentService
    interactions: InteractionService
    pipelines: PipelineRegistry


_ALL_CODES: tuple[ErrorCode, ...] = (
    *COMMON_CODES,
    *DB_CODES,
    *IDENTITY_CODES,
    *RBAC_CODES,
    *AUTH_CODES,
    *TASK_CODES,
    *MAIL_CODES,
    *SETTING_CODES,
    *CACHE_CODES,
    *EVENT_CODES,
    *PIPELINE_CODES,
    *CONTENT_CODES,
    *TERM_CODES,
    *COMMENT_CODES,
)


def _register_missing_codes() -> None:
    from inc.kernel.errors.registry import ErrorRegistry

    missing = [code for code in _ALL_CODES if not ErrorRegistry.has(code.code)]
    if missing:
        register_error_codes(*missing)


def _register_defaults() -> None:
    if SiteProfileSettings.slug not in setting_registry.keys():
        register_setting(SiteProfileSettings)
    if mail_template_registry.get("auth.password_reset") is None:
        register_mail_template(
            "auth.password_reset",
            "Reset your password",
            (
                "Use this link to reset your password: {reset_url}\n"
                "This link expires in {expires_minutes} minutes."
            ),
            PasswordResetMailContext,
        )


def _register_events(bus: EventBus) -> None:
    event_types = (
        *AUTH_EVENT_TYPES,
        *IDENTITY_EVENT_TYPES,
        *MAIL_EVENT_TYPES,
        *SETTING_EVENT_TYPES,
        *TASK_EVENT_TYPES,
        "audit.recorded",
        *RBAC_EVENT_TYPES,
        *CONTENT_EVENT_TYPES,
        *TAXONOMY_EVENT_TYPES,
        *COMMENT_EVENT_TYPES,
        "interaction.changed",
    )
    for event_type in event_types:
        if not bus.is_registered(event_type):
            bus.register(event_type)


async def _audit_domain_event(container: AppContainer, event: Event) -> None:
    """Map sensitive lifecycle events to the append-only audit stream."""
    payload = event.payload.model_dump(mode="json")
    actor_id = payload.get("actor_id") or payload.get("user_id")
    target_id = payload.get("user_id") or payload.get("mail_id")
    from uuid import UUID

    principal_id = UUID(str(actor_id)) if actor_id else UUID(int=0)
    from inc.kernel.security import Principal

    principal = Principal(
        id=principal_id,
        username="event-actor" if actor_id else "system-event",
        is_system_bot=not bool(actor_id),
    )
    target_uuid = UUID(str(target_id)) if target_id else None
    if event.type == "user.banned" and target_uuid is not None:
        await container.auth.revoke_all_for_user(target_uuid)
    await container.audit.record(
        event.type,
        principal,
        target_type="user"
        if payload.get("user_id")
        else "mail"
        if payload.get("mail_id")
        else None,
        target_id=target_uuid,
    )


def build_container(settings: Settings) -> AppContainer:
    _register_missing_codes()
    _register_defaults()
    if len(set(_EXTENSION_SLOT_KEYS)) != len(_EXTENSION_SLOT_KEYS):
        raise RuntimeError("duplicate extension slot key")
    database = create_database(settings)
    cache = build_cache(settings)
    event_bus = fresh_event_bus()
    _register_events(event_bus)
    pipelines = PipelineRegistry()
    register_content_pipelines(pipelines)
    register_taxonomy_pipelines(pipelines)
    register_comment_pipelines(pipelines)
    pipelines.validate_all()
    token_service = TokenService(settings)
    auth = AuthService(
        UoWExecutor(lambda: AuthUnitOfWork(database.session_factory)),
        token_service,
        cache,
        event_bus=event_bus,
    )
    identity = IdentityService(
        UoWExecutor(lambda: IdentityUnitOfWork(database.session_factory)), event_bus=event_bus
    )
    rbac = RBACService(
        UoWExecutor(lambda: RBACUnitOfWork(database.session_factory)), event_bus=event_bus
    )
    content = ContentService(
        UoWExecutor(lambda: ContentUnitOfWork(database.session_factory)),
        event_bus=event_bus,
        registry=declarative_content_type_registry,
    )
    taxonomy = TermService(
        UoWExecutor(lambda: TaxonomyUnitOfWork(database.session_factory)),
        event_bus=event_bus,
        content_registry=declarative_content_type_registry,
        content_exists=content.exists,
    )
    comments = CommentService(
        UoWExecutor(lambda: CommentUnitOfWork(database.session_factory)),
        cache,
        event_bus=event_bus,
        target_policy=_comment_target_policy,
        target_exists=content.exists,
    )
    content.set_term_filter(taxonomy.content_ids_for_filter)

    async def comment_stats(type_name: str, content_ids: Sequence[UUID]) -> dict[UUID, int]:
        stats = await comments.stats_for_targets(type_name, content_ids)
        return {content_id: item.count for content_id, item in stats.items()}

    content.set_comment_stats(comment_stats)
    interactions = InteractionService(
        UoWExecutor(lambda: InteractionUnitOfWork(database.session_factory)),
        target_exists=content.exists,
        event_bus=event_bus,
    )
    mail = MailService(
        UoWExecutor(lambda: MailUnitOfWork(database.session_factory)),
        event_bus=event_bus,
        settings=settings,
    )
    audit = AuditService(
        UoWExecutor(lambda: AuditUnitOfWork(database.session_factory)), event_bus=event_bus
    )
    runtime_settings = SettingsService(
        UoWExecutor(lambda: SettingsUnitOfWork(database.session_factory)),
        cache,
        event_bus=event_bus,
    )
    scheduler = TaskScheduler(
        UoWExecutor(lambda: TaskUnitOfWork(database.session_factory)),
        event_bus=event_bus,
        settings=settings,
    )
    container = AppContainer(
        settings=settings,
        database=database,
        cache=cache,
        event_bus=event_bus,
        token_service=token_service,
        identity=identity,
        rbac=rbac,
        auth=auth,
        mail=mail,
        audit=audit,
        runtime_settings=runtime_settings,
        scheduler=scheduler,
        content=content,
        taxonomy=taxonomy,
        comments=comments,
        interactions=interactions,
        pipelines=pipelines,
    )

    async def audit_handler(event: Event) -> None:
        await _audit_domain_event(container, event)

    async def interaction_handler(event: Event) -> None:
        payload = InteractionChangedPayload.model_validate(event.payload)
        await content.apply_interaction_change(
            payload.target_id,
            kind=payload.kind,
            numeric_value=payload.numeric_value,
            previous_value=payload.previous_value,
            existed=payload.existed,
            deleted=payload.deleted,
        )

    for event_type in (
        *AUTH_EVENT_TYPES,
        *IDENTITY_EVENT_TYPES,
        *MAIL_EVENT_TYPES,
        *SETTING_EVENT_TYPES,
        *RBAC_EVENT_TYPES,
        *CONTENT_EVENT_TYPES,
        *TAXONOMY_EVENT_TYPES,
        *COMMENT_EVENT_TYPES,
    ):
        event_bus.subscribe(event_type, audit_handler)
    event_bus.subscribe("interaction.changed", interaction_handler)

    async def reap(_principal: Principal) -> None:
        await scheduler.reap_orphans()

    async def retry_mail(principal: Principal) -> None:
        await mail.retry_failed(principal)

    async def purge_audit(principal: Principal) -> None:
        await audit.purge_old_logs(principal)

    async def purge_auth(principal: Principal) -> None:
        await auth.purge_expired_tokens(principal)

    async def purge_content(principal: Principal) -> None:
        await content.purge_trash(principal)

    async def purge_comments(principal: Principal) -> None:
        await comments.purge_orphans(principal)

    async def recount_comments(principal: Principal) -> None:
        await content.recount_comments(principal)

    scheduler.register_cron("tasks.reap_orphans", "*/5 * * * *", reap)
    scheduler.register_cron("mail.retry_failed", "*/5 * * * *", retry_mail)
    scheduler.register_cron("audit.purge_old_logs", "30 4 * * *", purge_audit)
    scheduler.register_cron("auth.purge_expired_tokens", "10 4 * * *", purge_auth)
    scheduler.register_cron("content.purge_trash", "50 4 * * *", purge_content)
    scheduler.register_cron("content.recount_comments", "20 5 * * *", recount_comments)
    scheduler.register_cron("comment.purge_orphans", "10 5 * * *", purge_comments)
    validate_capability_registry(ALL_CAPABILITY_ALIASES)
    capability_registry.freeze()
    event_bus.freeze()
    return container
