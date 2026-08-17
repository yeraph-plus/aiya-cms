"""Semantic community commands.

Commands are the only write boundary.  They update community facts, search
documents, idempotency records and the kernel outbox in one UoW.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from inc.capabilities.community.events import payload_for
from inc.capabilities.community.markdown import validate_markdown
from inc.capabilities.community.models import (
    CommunityDiscussion,
    CommunityDiscussionTag,
    CommunityIdempotencyRecord,
    CommunityPost,
    CommunitySearchDocument,
    CommunityTag,
    DiscussionDataEnvelope,
    IdempotencyResultEnvelope,
    PostDataEnvelope,
    TagMetadataEnvelope,
)
from inc.capabilities.community.ports import CommunityAuthorPort
from inc.capabilities.community.schemas import (
    CommunityAuthorDTO,
    CreateDiscussionInput,
    CreateReplyInput,
    CreateTagInput,
    DiscussionDTO,
    DiscussionTagDTO,
    PostDTO,
    PurgeArchivedDiscussionsInput,
    ReorderTagsInput,
    ReplaceDiscussionTagsInput,
    TagDTO,
    UpdateDiscussionInput,
    UpdatePostInput,
    UpdateTagInput,
)
from inc.capabilities.community.search import (
    SEARCH_PROFILE,
    markdown_search_text,
    title_search_text,
)
from inc.capabilities.community.slug import generate_discussion_slug
from inc.capabilities.community.types import DiscussionTemplateRegistry, DiscussionTemplateSpec
from inc.kernel.db import UnitOfWork, UoWFactory, new_uuid7
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

AUDIT_EVENT_KEY = "audit.entry.recorded.v1"

PERMISSION_CREATE = "community.discussions.create"
PERMISSION_REPLY = "community.discussions.reply"
PERMISSION_EDIT_OWN = "community.discussions.edit_own"
PERMISSION_MODERATE = "community.discussions.moderate"
PERMISSION_LOCK = "community.discussions.lock"
PERMISSION_ARCHIVE = "community.discussions.archive"
PERMISSION_POST_MODERATE = "community.posts.moderate"
PERMISSION_TAGS = "community.tags.manage"
PERMISSION_READ_ADMIN = "community.read_admin"
PERMISSION_SEARCH_REBUILD = "community.search.rebuild"
PERMISSION_PURGE = "community.purge"

_SLUG_RETRY_COUNT = 5
_TAG_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ICON_KEY = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_COLOR = re.compile(r"^(?:#[0-9a-fA-F]{6}|red|orange|yellow|green|blue|purple|gray)$")


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    templates: DiscussionTemplateRegistry
    author_port: CommunityAuthorPort
    permissions: frozenset[str] = frozenset()
    actor_type: str = "identity"
    actor_id: str | None = None
    trace_id: str | None = None


def _error(code: str, category: ErrorCategory, message: str) -> KernelError:
    return KernelError(code=code, category=category, message=message)


def _validation(code: str, message: str) -> KernelError:
    return _error(code, ErrorCategory.VALIDATION, message)


def _conflict(code: str, message: str) -> KernelError:
    return _error(code, ErrorCategory.CONFLICT, message)


def _forbidden(message: str) -> KernelError:
    return _error("community.forbidden", ErrorCategory.FORBIDDEN, message)


def _not_found(kind: str, value: Any) -> KernelError:
    return _error("community.not_found", ErrorCategory.NOT_FOUND, f"{kind} {value} was not found")


def _require(ctx: CommandContext, permission: str) -> None:
    if permission not in ctx.permissions:
        raise _forbidden(f"requires permission {permission}")


def _template(ctx: CommandContext, key: str) -> DiscussionTemplateSpec:
    try:
        return ctx.templates.require(key)
    except KernelError as exc:
        if exc.code == "community.unknown_template":
            raise _validation(exc.code, exc.message) from exc
        raise


def _now(ctx: CommandContext) -> datetime:
    return ctx.clock.utc_now()


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _required_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _check_title(spec: DiscussionTemplateSpec, title: str) -> str:
    normalized = title.strip()
    if len(normalized) < spec.title_min_length or len(normalized) > spec.title_max_length:
        raise _validation(
            "community.invalid_title",
            f"title must contain {spec.title_min_length} to {spec.title_max_length} characters",
        )
    if "\x00" in normalized or any(ord(char) < 0x20 for char in normalized):
        raise _validation("community.invalid_title", "title contains a control character")
    return normalized


def _validate_author_reference(author_type: str, author_id: str) -> None:
    if not author_type.strip() or not author_id.strip():
        raise _validation("community.author_invalid", "author reference is empty")


async def _validate_author(ctx: CommandContext, author_type: str, author_id: str) -> None:
    _validate_author_reference(author_type, author_id)
    try:
        validator = getattr(ctx.author_port, "validate", None) or getattr(
            ctx.author_port, "validate_author", None
        )
        if validator is None:
            validator = getattr(ctx.author_port, "exists", None)
        if validator is None:
            raise RuntimeError("author port has no validation method")
        allowed = await validator(author_type, author_id)
    except KernelError:
        raise
    except Exception as exc:  # noqa: BLE001 - provider boundary
        raise _error(
            "community.author_provider_unavailable",
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            "community author provider is unavailable",
        ) from exc
    if not allowed:
        raise _validation("community.author_not_found", "author reference does not exist")


async def _project_author(
    ctx: CommandContext, author_type: str, author_id: str
) -> CommunityAuthorDTO | None:
    try:
        projector = getattr(ctx.author_port, "project", None) or getattr(
            ctx.author_port, "project_authors", None
        )
        if projector is None:
            raise RuntimeError("author port has no projection method")
        values = await projector(((author_type, author_id),))
    except Exception as exc:  # noqa: BLE001 - provider boundary
        raise _error(
            "community.author_provider_unavailable",
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            "community author provider is unavailable",
        ) from exc
    return cast(CommunityAuthorDTO | None, values.get((author_type, author_id)))


async def _project_authors(
    ctx: CommandContext, refs: list[tuple[str, str]]
) -> dict[tuple[str, str], CommunityAuthorDTO]:
    if not refs:
        return {}
    try:
        projector = getattr(ctx.author_port, "project", None) or getattr(
            ctx.author_port, "project_authors", None
        )
        if projector is None:
            raise RuntimeError("author port has no projection method")
        return cast(
            dict[tuple[str, str], CommunityAuthorDTO],
            await projector(tuple(dict.fromkeys(refs))),
        )
    except Exception as exc:  # noqa: BLE001 - provider boundary
        raise _error(
            "community.author_provider_unavailable",
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            "community author provider is unavailable",
        ) from exc


def _request_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _idempotency_digest(key: str | None) -> str | None:
    if key is None:
        return None
    if not key.strip() or len(key) > 200 or any(ord(char) < 0x20 for char in key):
        raise _validation("community.idempotency_key_invalid", "invalid idempotency key")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def _existing_idempotency(
    uow: UnitOfWork,
    *,
    scope: str,
    key_digest: str | None,
    request_digest: str,
) -> CommunityIdempotencyRecord | None:
    if key_digest is None:
        return None
    row = (
        await uow.session.execute(
            select(CommunityIdempotencyRecord).where(
                CommunityIdempotencyRecord.scope == scope,
                CommunityIdempotencyRecord.idempotency_key_digest == key_digest,
            )
        )
    ).scalar_one_or_none()
    if row is not None and row.result.request_digest != request_digest:
        raise _conflict(
            "community.idempotency_conflict",
            "idempotency key was already used with a different request",
        )
    return cast(CommunityIdempotencyRecord, row)


def _save_idempotency(
    uow: UnitOfWork,
    *,
    scope: str,
    key_digest: str | None,
    request_digest: str,
    resource_type: str,
    resource_id: str,
) -> None:
    if key_digest is None:
        return
    uow.session.add(
        CommunityIdempotencyRecord(
            id=new_uuid7(),
            scope=scope,
            idempotency_key_digest=key_digest,
            result=IdempotencyResultEnvelope(
                resource_type=resource_type,
                resource_id=resource_id,
                request_digest=request_digest,
            ),
        )
    )


async def _emit(ctx: CommandContext, uow: UnitOfWork, key: str, **values: Any) -> None:
    now = _now(ctx)
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=new_uuid7(),
            event_key=key,
            occurred_at=now,
            producer="community",
            aggregate_type="community",
            aggregate_id=str(
                values.get("discussion_id")
                or values.get("post_id")
                or values.get("tag_id")
                or "community"
            ),
            aggregate_version=values.get("version"),
            trace_id=ctx.trace_id,
            payload=payload_for(key, **values),
        ),
    )


async def _audit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    now = _now(ctx)
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=new_uuid7(),
            event_key=AUDIT_EVENT_KEY,
            occurred_at=now,
            producer="community",
            aggregate_type=target_type,
            aggregate_id=target_id,
            trace_id=ctx.trace_id,
            payload={
                "action": action,
                "outcome": "success",
                "occurred_at": now.isoformat(),
                "actor_type": ctx.actor_type if ctx.actor_id else None,
                "actor_id": ctx.actor_id,
                "target_type": target_type,
                "target_id": target_id,
                "trace_id": ctx.trace_id,
                "details": details or {},
            },
        ),
    )


async def _commit(uow: UnitOfWork, code: str = "community.state_conflict") -> None:
    try:
        await uow.commit()
    except IntegrityError as exc:
        raise _conflict(code, "community state changed or a constraint was violated") from exc


async def _get_discussion(uow: UnitOfWork, discussion_id: uuid.UUID) -> CommunityDiscussion:
    row = await uow.session.get(CommunityDiscussion, discussion_id, with_for_update=True)
    if row is None:
        raise _not_found("discussion", discussion_id)
    return cast(CommunityDiscussion, row)


async def _get_post(uow: UnitOfWork, post_id: uuid.UUID) -> CommunityPost:
    row = await uow.session.get(CommunityPost, post_id, with_for_update=True)
    if row is None:
        raise _not_found("post", post_id)
    return cast(CommunityPost, row)


async def _get_tag(uow: UnitOfWork, tag_id: uuid.UUID) -> CommunityTag:
    row = await uow.session.get(CommunityTag, tag_id, with_for_update=True)
    if row is None:
        raise _not_found("tag", tag_id)
    return cast(CommunityTag, row)


def _check_version(row: Any, expected: int) -> None:
    if row.version != expected:
        raise _conflict(
            "community.version_conflict",
            f"expected version {expected}, found {row.version}",
        )


def _check_discussion_transition(
    spec: DiscussionTemplateSpec, row: CommunityDiscussion, target: str
) -> None:
    if row.status == target:
        return
    if not spec.can_discussion_transition(row.status, target):
        raise _conflict(
            "community.invalid_transition",
            f"cannot move discussion from {row.status!r} to {target!r}",
        )


def _check_post_transition(spec: DiscussionTemplateSpec, row: CommunityPost, target: str) -> None:
    if row.status == target:
        return
    if not spec.can_post_transition(row.status, target):
        raise _conflict(
            "community.invalid_transition",
            f"cannot move post from {row.status!r} to {target!r}",
        )


async def _load_tags(
    uow: UnitOfWork,
    spec: DiscussionTemplateSpec,
    tag_ids: list[uuid.UUID],
    *,
    allow_empty: bool = False,
) -> list[CommunityTag]:
    if len(set(tag_ids)) != len(tag_ids):
        raise _validation("community.tag_limit_exceeded", "duplicate tag ids are not allowed")
    if not tag_ids and not allow_empty and spec.min_primary_tags > 0:
        raise _validation("community.tag_required", "a primary tag is required")
    rows = list(
        (await uow.session.execute(select(CommunityTag).where(CommunityTag.id.in_(tag_ids))))
        .scalars()
        .all()
    )
    if len(rows) != len(tag_ids):
        raise _validation("community.tag_not_found", "one or more tags do not exist")
    by_id = {row.id: row for row in rows}
    ordered = [by_id[tag_id] for tag_id in tag_ids]
    if any(row.status != "active" for row in ordered):
        raise _validation("community.tag_archived", "archived tags cannot be newly assigned")
    primary = [row for row in ordered if row.kind == "primary"]
    secondary = [row for row in ordered if row.kind == "secondary"]
    if not spec.min_primary_tags <= len(primary) <= spec.max_primary_tags:
        code = (
            "community.tag_required"
            if len(primary) < spec.min_primary_tags
            else "community.tag_limit_exceeded"
        )
        raise _validation(code, "primary tag count is outside the template limits")
    if not spec.min_secondary_tags <= len(secondary) <= spec.max_secondary_tags:
        raise _validation(
            "community.tag_limit_exceeded", "secondary tag count is outside the template limits"
        )
    return ordered


async def _replace_tags(
    ctx: CommandContext,
    uow: UnitOfWork,
    discussion: CommunityDiscussion,
    spec: DiscussionTemplateSpec,
    tag_ids: list[uuid.UUID],
) -> list[CommunityTag]:
    tags = await _load_tags(uow, spec, tag_ids)
    existing = list(
        (
            await uow.session.execute(
                select(CommunityDiscussionTag).where(
                    CommunityDiscussionTag.discussion_id == discussion.id
                )
            )
        )
        .scalars()
        .all()
    )
    for row in existing:
        await uow.session.delete(row)
    await uow.session.flush()
    now = _now(ctx)
    for position, tag in enumerate(tags):
        uow.session.add(
            CommunityDiscussionTag(
                id=new_uuid7(),
                discussion_id=discussion.id,
                tag_id=tag.id,
                position=position,
                assigned_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    return tags


async def _sync_search_documents(
    uow: UnitOfWork, discussion: CommunityDiscussion, *, body_limit: int = 262144
) -> None:
    old = list(
        (
            await uow.session.execute(
                select(CommunitySearchDocument).where(
                    CommunitySearchDocument.discussion_id == discussion.id
                )
            )
        )
        .scalars()
        .all()
    )
    for document in old:
        await uow.session.delete(document)
    await uow.session.flush()
    if discussion.status != "published":
        return
    now = discussion.updated_at
    uow.session.add(
        CommunitySearchDocument(
            id=new_uuid7(),
            discussion_id=discussion.id,
            document_kind="title",
            search_profile=SEARCH_PROFILE,
            normalized_text=title_search_text(discussion.title),
            source_version=discussion.version,
            created_at=now,
            updated_at=now,
        )
    )
    posts = list(
        (
            await uow.session.execute(
                select(CommunityPost)
                .where(
                    CommunityPost.discussion_id == discussion.id,
                    CommunityPost.status == "published",
                )
                .order_by(CommunityPost.number, CommunityPost.id)
            )
        )
        .scalars()
        .all()
    )
    for post in posts:
        uow.session.add(
            CommunitySearchDocument(
                id=new_uuid7(),
                discussion_id=discussion.id,
                post_id=post.id,
                document_kind="post",
                search_profile=SEARCH_PROFILE,
                normalized_text=markdown_search_text(post.body, max_bytes=body_limit),
                source_version=post.version,
                created_at=now,
                updated_at=now,
            )
        )


async def _recompute_summary(
    uow: UnitOfWork,
    discussion: CommunityDiscussion,
    *,
    changed_post: CommunityPost | None = None,
) -> None:
    with uow.session.no_autoflush:
        posts = list(
            (
                await uow.session.execute(
                    select(CommunityPost)
                    .where(
                        CommunityPost.discussion_id == discussion.id,
                        CommunityPost.status == "published",
                    )
                    .order_by(CommunityPost.number, CommunityPost.id)
                )
            )
            .scalars()
            .all()
        )
    if changed_post is not None:
        posts = [post for post in posts if post.id != changed_post.id]
        if changed_post.status == "published":
            posts.append(changed_post)
        posts.sort(key=lambda post: (post.number, str(post.id)))
    first = next((post for post in posts if post.number == 1), None)
    discussion.reply_count = max(0, len(posts) - (1 if first is not None else 0))
    discussion.first_post_id = first.id if first is not None else discussion.first_post_id
    last = max(
        posts,
        key=lambda post: (
            _ensure_utc(post.published_at) or datetime.min.replace(tzinfo=UTC),
            post.number,
            str(post.id),
        ),
        default=None,
    )
    discussion.last_post_id = last.id if last is not None else None
    discussion.last_posted_at = _ensure_utc(last.published_at) if last is not None else None


async def _discussion_tags(
    uow: UnitOfWork, discussion_id: uuid.UUID
) -> list[tuple[CommunityTag, int]]:
    return list(
        (
            await uow.session.execute(
                select(CommunityTag, CommunityDiscussionTag.position)
                .join(CommunityDiscussionTag, CommunityDiscussionTag.tag_id == CommunityTag.id)
                .where(CommunityDiscussionTag.discussion_id == discussion_id)
                .order_by(CommunityDiscussionTag.position, CommunityTag.name, CommunityTag.id)
            )
        ).all()
    )


def _tag_dto(row: CommunityTag, *, count: int = 0, position: int | None = None) -> TagDTO:
    return TagDTO(
        id=str(row.id),
        kind=row.kind,
        name=row.name,
        slug=row.slug,
        description=row.description,
        color=row.color,
        icon_key=row.icon_key,
        parent_id=str(row.parent_id) if row.parent_id else None,
        position=row.position if position is None else position,
        status=row.status,
        published_discussion_count=count,
        version=row.version,
    )


async def _discussion_dto(
    ctx: CommandContext,
    uow: UnitOfWork,
    row: CommunityDiscussion,
    *,
    author: CommunityAuthorDTO | None = None,
) -> DiscussionDTO:
    spec = ctx.templates.require(row.template_key)
    tags = await _discussion_tags(uow, row.id)
    tag_dtos = [
        DiscussionTagDTO(
            id=str(tag.id),
            kind=tag.kind,
            name=tag.name,
            slug=tag.slug,
            description=tag.description,
            color=tag.color,
            icon_key=tag.icon_key,
            parent_id=str(tag.parent_id) if tag.parent_id else None,
            position=position,
            status=tag.status,
        )
        for tag, position in tags
    ]
    if author is None:
        author = await _project_author(ctx, row.author_type, row.author_id)
    return DiscussionDTO(
        id=str(row.id),
        template_key=row.template_key,
        schema_version=row.schema_version,
        title=row.title,
        slug=row.slug,
        status=row.status,
        author_type=row.author_type,
        author_id=row.author_id,
        author=author,
        data=spec.public_data(dict(row.data.payload)),
        is_locked=row.is_locked,
        locked_at=_ensure_utc(row.locked_at),
        locked_by_type=row.locked_by_type,
        locked_by_id=row.locked_by_id,
        first_post_id=str(row.first_post_id) if row.first_post_id else None,
        last_post_id=str(row.last_post_id) if row.last_post_id else None,
        reply_count=row.reply_count,
        last_posted_at=_ensure_utc(row.last_posted_at),
        version=row.version,
        created_at=_required_utc(row.created_at),
        updated_at=_required_utc(row.updated_at),
        published_at=_ensure_utc(row.published_at),
        hidden_at=_ensure_utc(row.hidden_at),
        archived_at=_ensure_utc(row.archived_at),
        tags=tag_dtos,
    )


async def _post_dto(
    ctx: CommandContext,
    row: CommunityPost,
    spec: DiscussionTemplateSpec,
    *,
    author: CommunityAuthorDTO | None = None,
) -> PostDTO:
    if author is None:
        author = await _project_author(ctx, row.author_type, row.author_id)
    visible = row.status == "published"
    return PostDTO(
        id=str(row.id),
        discussion_id=str(row.discussion_id),
        number=row.number,
        post_type=row.post_type,
        status=row.status,
        author_type=row.author_type,
        author_id=row.author_id,
        author=author,
        body=row.body if visible and row.status != "deleted" else None,
        body_format="markdown",
        body_profile=row.body_profile,
        schema_version=row.schema_version,
        data=(
            spec.public_data(dict(row.data.payload)) if visible and row.status != "deleted" else {}
        ),
        version=row.version,
        created_at=_required_utc(row.created_at),
        updated_at=_required_utc(row.updated_at),
        edited_at=_ensure_utc(row.edited_at),
        published_at=_ensure_utc(row.published_at),
        hidden_at=_ensure_utc(row.hidden_at),
        deleted_at=_ensure_utc(row.deleted_at),
    )


class CreateDiscussion:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: CreateDiscussionInput) -> DiscussionDTO:
        ctx = self._ctx
        spec = _template(ctx, input_.template_key)
        _require(ctx, spec.create_access_key)
        title = _check_title(spec, input_.title)
        document = validate_markdown(input_.body, max_bytes=spec.body_max_bytes)
        discussion_payload = spec.validate_discussion_data(input_.data)
        post_payload = spec.validate_post_data(input_.post_data)
        await _validate_author(ctx, input_.author_type, input_.author_id)
        request_digest = _request_digest(
            {
                "template_key": input_.template_key,
                "title": title,
                "body": document.source,
                "data": discussion_payload,
                "post_data": post_payload,
                "tag_ids": [str(tag_id) for tag_id in input_.tag_ids],
                "author_type": input_.author_type,
                "author_id": input_.author_id,
            }
        )
        key_digest = _idempotency_digest(input_.idempotency_key)

        for _ in range(_SLUG_RETRY_COUNT):
            now = _now(ctx)
            try:
                async with ctx.uow_factory() as uow:
                    replay = await _existing_idempotency(
                        uow,
                        scope="discussion.create",
                        key_digest=key_digest,
                        request_digest=request_digest,
                    )
                    if replay is not None:
                        row = await uow.session.get(
                            CommunityDiscussion, uuid.UUID(replay.result.resource_id)
                        )
                        if row is None:
                            raise _conflict(
                                "community.idempotency_result_missing",
                                "idempotency result no longer points to a discussion",
                            )
                        return await _discussion_dto(ctx, uow, row)
                    status = spec.initial_discussion_status(ctx.permissions)
                    post_status = spec.initial_first_post_status(ctx.permissions)
                    discussion_id = new_uuid7()
                    post_id = new_uuid7()
                    discussion = CommunityDiscussion(
                        id=discussion_id,
                        template_key=spec.template_key,
                        schema_version=spec.discussion_data_schema_version,
                        title=title,
                        slug=generate_discussion_slug(title),
                        status=status,
                        author_type=input_.author_type,
                        author_id=input_.author_id,
                        data=DiscussionDataEnvelope(
                            schema_version=spec.discussion_data_schema_version,
                            payload=discussion_payload,
                        ),
                        first_post_id=post_id,
                        last_post_id=post_id if status == "published" else None,
                        reply_count=0,
                        last_posted_at=now if status == "published" else None,
                        version=1,
                        published_at=now if status == "published" else None,
                        created_at=now,
                        updated_at=now,
                    )
                    post = CommunityPost(
                        id=post_id,
                        discussion_id=discussion_id,
                        number=1,
                        post_type="comment",
                        status=post_status,
                        author_type=input_.author_type,
                        author_id=input_.author_id,
                        body=document.source,
                        body_profile=spec.body_profile,
                        schema_version=spec.post_data_schema_version,
                        data=PostDataEnvelope(
                            schema_version=spec.post_data_schema_version,
                            payload=post_payload,
                        ),
                        version=1,
                        published_at=now if post_status == "published" else None,
                        created_at=now,
                        updated_at=now,
                    )
                    uow.session.add_all((discussion, post))
                    await uow.session.flush()
                    tags = await _replace_tags(ctx, uow, discussion, spec, input_.tag_ids)
                    await _sync_search_documents(uow, discussion, body_limit=spec.body_max_bytes)
                    await _emit(
                        ctx,
                        uow,
                        "community.discussion_created.v1",
                        discussion_id=str(discussion.id),
                        status=discussion.status,
                        version=discussion.version,
                    )
                    await _emit(
                        ctx,
                        uow,
                        "community.post_created.v1",
                        discussion_id=str(discussion.id),
                        post_id=str(post.id),
                        status=post.status,
                        version=post.version,
                    )
                    if discussion.status == "published":
                        await _emit(
                            ctx,
                            uow,
                            "community.discussion_published.v1",
                            discussion_id=str(discussion.id),
                            status=discussion.status,
                            version=discussion.version,
                        )
                    if post.status == "published":
                        await _emit(
                            ctx,
                            uow,
                            "community.post_published.v1",
                            discussion_id=str(discussion.id),
                            post_id=str(post.id),
                            status=post.status,
                            version=post.version,
                        )
                    await _emit(
                        ctx,
                        uow,
                        "community.tags_replaced.v1",
                        discussion_id=str(discussion.id),
                        version=discussion.version,
                        tag_ids=tuple(str(tag.id) for tag in tags),
                    )
                    await _audit(
                        ctx,
                        uow,
                        action="community.discussion.create",
                        target_type="discussion",
                        target_id=str(discussion.id),
                        details={"status": discussion.status, "tag_count": len(tags)},
                    )
                    _save_idempotency(
                        uow,
                        scope="discussion.create",
                        key_digest=key_digest,
                        request_digest=request_digest,
                        resource_type="discussion",
                        resource_id=str(discussion.id),
                    )
                    await _commit(uow, "community.slug_generation_failed")
                    return await _discussion_dto(ctx, uow, discussion)
            except IntegrityError:
                continue
            except KernelError as exc:
                if exc.code == "community.slug_generation_failed":
                    continue
                raise
        raise _conflict(
            "community.slug_generation_failed", "could not allocate a unique discussion slug"
        )


class UpdateDiscussion:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self, discussion_id: uuid.UUID, input_: UpdateDiscussionInput
    ) -> DiscussionDTO:
        ctx = self._ctx
        now = _now(ctx)
        async with ctx.uow_factory() as uow:
            row = await _get_discussion(uow, discussion_id)
            spec = _template(ctx, row.template_key)
            own = (
                ctx.actor_type == row.author_type
                and ctx.actor_id is not None
                and ctx.actor_id == row.author_id
            )
            if not own:
                _require(ctx, spec.moderate_access_key)
            else:
                _require(ctx, spec.edit_access_key)
            _check_version(row, input_.expected_version)
            changed: list[str] = []
            if input_.title is not None:
                title = _check_title(spec, input_.title)
                if title != row.title:
                    row.title = title
                    changed.append("title")
            if input_.data is not None:
                payload = spec.validate_discussion_data(input_.data)
                if payload != row.data.payload:
                    row.data = DiscussionDataEnvelope(
                        schema_version=spec.discussion_data_schema_version, payload=payload
                    )
                    changed.append("data")
            if not changed:
                raise _validation("community.empty_update", "nothing to update")
            row.version += 1
            row.updated_at = now
            await uow.session.flush()
            await _sync_search_documents(uow, row, body_limit=spec.body_max_bytes)
            await _emit(
                ctx,
                uow,
                "community.discussion_updated.v1",
                discussion_id=str(row.id),
                status=row.status,
                version=row.version,
            )
            await _audit(
                ctx,
                uow,
                action="community.discussion.update",
                target_type="discussion",
                target_id=str(row.id),
                details={"changed": changed},
            )
            await _commit(uow)
            return await _discussion_dto(ctx, uow, row)
        raise RuntimeError("community discussion update did not execute")


class SubmitDiscussion:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, discussion_id: uuid.UUID) -> DiscussionDTO:
        return await _transition_discussion(self._ctx, discussion_id, "pending", "submit")


class PublishDiscussion:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, discussion_id: uuid.UUID) -> DiscussionDTO:
        ctx = self._ctx
        now = _now(ctx)
        async with ctx.uow_factory() as uow:
            row = await _get_discussion(uow, discussion_id)
            spec = _template(ctx, row.template_key)
            _require(ctx, spec.moderate_access_key)
            if row.status == "published":
                return await _discussion_dto(ctx, uow, row)
            _check_discussion_transition(spec, row, "published")
            first = await uow.session.get(CommunityPost, row.first_post_id, with_for_update=True)
            if first is None or first.status in {"hidden", "deleted"}:
                raise _conflict(
                    "community.first_post_not_publishable",
                    "published discussion needs a published first post",
                )
            if first.status != "published":
                _check_post_transition(spec, first, "published")
                first.status = "published"
                first.published_at = now
                first.version += 1
                first.updated_at = now
                await uow.session.flush()
                await _emit(
                    ctx,
                    uow,
                    "community.post_published.v1",
                    discussion_id=str(row.id),
                    post_id=str(first.id),
                    status=first.status,
                    version=first.version,
                )
            row.status = "published"
            row.published_at = row.published_at or now
            row.hidden_at = None
            row.archived_at = None
            row.version += 1
            row.updated_at = now
            await _recompute_summary(uow, row, changed_post=first)
            if row.last_post_id is None:
                raise _conflict(
                    "community.first_post_not_publishable",
                    "published discussion has no published post",
                )
            await uow.session.flush()
            await _sync_search_documents(uow, row, body_limit=spec.body_max_bytes)
            await _emit(
                ctx,
                uow,
                "community.discussion_published.v1",
                discussion_id=str(row.id),
                status=row.status,
                version=row.version,
            )
            await _audit(
                ctx,
                uow,
                action="community.discussion.publish",
                target_type="discussion",
                target_id=str(row.id),
            )
            await _commit(uow)
            return await _discussion_dto(ctx, uow, row)
        raise RuntimeError("community discussion publish did not execute")


class HideDiscussion:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, discussion_id: uuid.UUID) -> DiscussionDTO:
        return await _transition_discussion(self._ctx, discussion_id, "hidden", "hide")


class RestoreDiscussion:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, discussion_id: uuid.UUID) -> DiscussionDTO:
        return await _transition_discussion(self._ctx, discussion_id, "published", "restore")


class ArchiveDiscussion:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, discussion_id: uuid.UUID) -> DiscussionDTO:
        ctx = self._ctx
        return await _transition_discussion(ctx, discussion_id, "archived", "archive")


async def _transition_discussion(
    ctx: CommandContext,
    discussion_id: uuid.UUID,
    target: str,
    action: str,
) -> DiscussionDTO:
    now = _now(ctx)
    async with ctx.uow_factory() as uow:
        row = await _get_discussion(uow, discussion_id)
        spec = _template(ctx, row.template_key)
        _require(
            ctx,
            spec.archive_access_key if target == "archived" else spec.moderate_access_key,
        )
        if row.status == target:
            return await _discussion_dto(ctx, uow, row)
        _check_discussion_transition(spec, row, target)
        if target == "pending":
            first = await uow.session.get(CommunityPost, row.first_post_id, with_for_update=True)
            if first is not None and first.status == "pending":
                pass
            elif first is not None and first.status == "hidden":
                raise _conflict(
                    "community.first_post_not_published",
                    "a hidden first post cannot be submitted",
                )
            elif first is not None and first.status == "draft":
                first.status = "pending"
                first.version += 1
                first.updated_at = now
        row.status = target
        row.version += 1
        row.updated_at = now
        if target == "hidden":
            row.hidden_at = now
        elif target == "published":
            first = await uow.session.get(CommunityPost, row.first_post_id)
            if first is None or first.status != "published":
                raise _conflict(
                    "community.first_post_not_published",
                    "discussion restore requires a published first post",
                )
            row.published_at = row.published_at or now
            row.hidden_at = None
            row.archived_at = None
            await _recompute_summary(uow, row)
        elif target == "archived":
            row.archived_at = now
        await uow.session.flush()
        await _sync_search_documents(uow, row, body_limit=spec.body_max_bytes)
        event_key = {
            "hidden": "community.discussion_hidden.v1",
            "archived": "community.discussion_archived.v1",
            "published": "community.discussion_published.v1",
        }.get(target, "community.discussion_updated.v1")
        await _emit(
            ctx, uow, event_key, discussion_id=str(row.id), status=row.status, version=row.version
        )
        await _audit(
            ctx,
            uow,
            action=f"community.discussion.{action}",
            target_type="discussion",
            target_id=str(row.id),
        )
        await _commit(uow)
        return await _discussion_dto(ctx, uow, row)
    raise RuntimeError("community discussion transition did not execute")


class LockDiscussion:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self, discussion_id: uuid.UUID, expected_version: int | None = None
    ) -> DiscussionDTO:
        return await _lock_discussion(self._ctx, discussion_id, True, expected_version)


class UnlockDiscussion:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self, discussion_id: uuid.UUID, expected_version: int | None = None
    ) -> DiscussionDTO:
        return await _lock_discussion(self._ctx, discussion_id, False, expected_version)


async def _lock_discussion(
    ctx: CommandContext, discussion_id: uuid.UUID, locked: bool, expected_version: int | None
) -> DiscussionDTO:
    now = _now(ctx)
    async with ctx.uow_factory() as uow:
        row = await _get_discussion(uow, discussion_id)
        spec = _template(ctx, row.template_key)
        _require(ctx, spec.lock_access_key)
        if expected_version is not None:
            _check_version(row, expected_version)
        if row.is_locked == locked:
            return await _discussion_dto(ctx, uow, row)
        row.is_locked = locked
        row.locked_at = now if locked else None
        row.locked_by_type = ctx.actor_type if locked else None
        row.locked_by_id = ctx.actor_id if locked else None
        row.version += 1
        row.updated_at = now
        await _emit(
            ctx,
            uow,
            "community.discussion_lock_changed.v1",
            discussion_id=str(row.id),
            status=row.status,
            version=row.version,
            is_locked=row.is_locked,
        )
        await _audit(
            ctx,
            uow,
            action="community.discussion.lock" if locked else "community.discussion.unlock",
            target_type="discussion",
            target_id=str(row.id),
        )
        await _commit(uow)
        return await _discussion_dto(ctx, uow, row)
    raise RuntimeError("community discussion lock did not execute")


class ReplaceDiscussionTags:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self, discussion_id: uuid.UUID, input_: ReplaceDiscussionTagsInput
    ) -> DiscussionDTO:
        ctx = self._ctx
        now = _now(ctx)
        async with ctx.uow_factory() as uow:
            row = await _get_discussion(uow, discussion_id)
            spec = _template(ctx, row.template_key)
            _require(ctx, spec.tags_access_key)
            _check_version(row, input_.expected_version)
            tags = await _replace_tags(ctx, uow, row, spec, input_.tag_ids)
            row.version += 1
            row.updated_at = now
            await _emit(
                ctx,
                uow,
                "community.tags_replaced.v1",
                discussion_id=str(row.id),
                version=row.version,
                tag_ids=tuple(str(tag.id) for tag in tags),
            )
            await _audit(
                ctx,
                uow,
                action="community.discussion.tags_replace",
                target_type="discussion",
                target_id=str(row.id),
                details={"tag_ids": [str(tag.id) for tag in tags]},
            )
            await _commit(uow)
            return await _discussion_dto(ctx, uow, row)
        raise RuntimeError("community tag replacement did not execute")


class CreateReply:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: CreateReplyInput) -> PostDTO:
        ctx = self._ctx
        key_digest = _idempotency_digest(input_.idempotency_key)
        request_digest = _request_digest(
            {
                "discussion_id": str(input_.discussion_id),
                "body": input_.body.replace("\r\n", "\n").replace("\r", "\n"),
                "data": input_.data,
                "author_type": input_.author_type,
                "author_id": input_.author_id,
            }
        )
        await _validate_author(ctx, input_.author_type, input_.author_id)
        async with ctx.uow_factory() as uow:
            replay = await _existing_idempotency(
                uow,
                scope="reply.create",
                key_digest=key_digest,
                request_digest=request_digest,
            )
            if replay is not None:
                row = await uow.session.get(CommunityPost, uuid.UUID(replay.result.resource_id))
                if row is None:
                    raise _conflict(
                        "community.idempotency_result_missing",
                        "idempotency result no longer points to a post",
                    )
                discussion = await _get_discussion(uow, row.discussion_id)
                spec = _template(ctx, discussion.template_key)
                _require(ctx, spec.reply_access_key)
                return await _post_dto(ctx, row, spec)
            discussion = await _get_discussion(uow, input_.discussion_id)
            spec = _template(ctx, discussion.template_key)
            _require(ctx, spec.reply_access_key)
            if discussion.status != "published":
                raise _conflict(
                    "community.invalid_transition", "replies require a published discussion"
                )
            if discussion.is_locked and spec.moderate_access_key not in ctx.permissions:
                raise _conflict("community.discussion_locked", "discussion is locked")
            document = validate_markdown(input_.body, max_bytes=spec.reply_body_max_bytes)
            payload = spec.validate_post_data(input_.data)
            max_number = (
                await uow.session.execute(
                    select(func.max(CommunityPost.number)).where(
                        CommunityPost.discussion_id == discussion.id
                    )
                )
            ).scalar_one()
            number = int(max_number or 0) + 1
            now = _now(ctx)
            status = spec.initial_post_status(ctx.permissions)
            post = CommunityPost(
                id=new_uuid7(),
                discussion_id=discussion.id,
                number=number,
                post_type="comment",
                status=status,
                author_type=input_.author_type,
                author_id=input_.author_id,
                body=document.source,
                body_profile=spec.body_profile,
                schema_version=spec.post_data_schema_version,
                data=PostDataEnvelope(
                    schema_version=spec.post_data_schema_version, payload=payload
                ),
                version=1,
                published_at=now if status == "published" else None,
                created_at=now,
                updated_at=now,
            )
            uow.session.add(post)
            await uow.session.flush()
            if status == "published":
                discussion.version += 1
                discussion.updated_at = now
                await _recompute_summary(uow, discussion, changed_post=post)
            await _sync_search_documents(uow, discussion, body_limit=spec.reply_body_max_bytes)
            await _emit(
                ctx,
                uow,
                "community.post_created.v1",
                discussion_id=str(discussion.id),
                post_id=str(post.id),
                status=post.status,
                version=post.version,
            )
            if post.status == "published":
                await _emit(
                    ctx,
                    uow,
                    "community.post_published.v1",
                    discussion_id=str(discussion.id),
                    post_id=str(post.id),
                    status=post.status,
                    version=post.version,
                )
            await _audit(
                ctx,
                uow,
                action="community.reply.create",
                target_type="post",
                target_id=str(post.id),
            )
            _save_idempotency(
                uow,
                scope="reply.create",
                key_digest=key_digest,
                request_digest=request_digest,
                resource_type="post",
                resource_id=str(post.id),
            )
            await _commit(uow)
            return await _post_dto(ctx, post, spec)
        raise RuntimeError("community reply creation did not execute")


class UpdatePost:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, post_id: uuid.UUID, input_: UpdatePostInput) -> PostDTO:
        ctx = self._ctx
        now = _now(ctx)
        async with ctx.uow_factory() as uow:
            row = await _get_post(uow, post_id)
            discussion = await _get_discussion(uow, row.discussion_id)
            spec = _template(ctx, discussion.template_key)
            own = (
                ctx.actor_type == row.author_type
                and ctx.actor_id is not None
                and ctx.actor_id == row.author_id
            )
            if own:
                _require(ctx, spec.edit_access_key)
            else:
                _require(ctx, spec.moderate_access_key)
            _check_version(row, input_.expected_version)
            if row.status == "deleted":
                raise _conflict("community.invalid_transition", "deleted posts cannot be edited")
            changed = False
            if input_.body is not None:
                document = validate_markdown(input_.body, max_bytes=spec.reply_body_max_bytes)
                if document.source != row.body:
                    row.body = document.source
                    changed = True
            if input_.data is not None:
                payload = spec.validate_post_data(input_.data)
                if payload != row.data.payload:
                    row.data = PostDataEnvelope(
                        schema_version=spec.post_data_schema_version, payload=payload
                    )
                    changed = True
            if not changed:
                raise _validation("community.empty_update", "nothing to update")
            row.version += 1
            row.edited_at = now
            row.updated_at = now
            await uow.session.flush()
            await _sync_search_documents(uow, discussion, body_limit=spec.reply_body_max_bytes)
            await _emit(
                ctx,
                uow,
                "community.discussion_updated.v1",
                discussion_id=str(discussion.id),
                status=discussion.status,
                version=discussion.version,
            )
            await _audit(
                ctx, uow, action="community.post.update", target_type="post", target_id=str(row.id)
            )
            await _commit(uow)
            return await _post_dto(ctx, row, spec)
        raise RuntimeError("community post update did not execute")


class ApprovePost:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, post_id: uuid.UUID) -> PostDTO:
        return await _transition_post(self._ctx, post_id, "published", "approve")


class HidePost:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, post_id: uuid.UUID) -> PostDTO:
        return await _transition_post(self._ctx, post_id, "hidden", "hide")


class DeletePost:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, post_id: uuid.UUID) -> PostDTO:
        return await _transition_post(self._ctx, post_id, "deleted", "delete")


async def _transition_post(
    ctx: CommandContext, post_id: uuid.UUID, target: str, action: str
) -> PostDTO:
    now = _now(ctx)
    async with ctx.uow_factory() as uow:
        row = await _get_post(uow, post_id)
        discussion = await _get_discussion(uow, row.discussion_id)
        spec = _template(ctx, discussion.template_key)
        _require(ctx, spec.moderate_access_key)
        if row.status == target:
            return await _post_dto(ctx, row, spec)
        _check_post_transition(spec, row, target)
        discussion_published = False
        row.status = target
        row.version += 1
        row.updated_at = now
        if target == "published":
            row.published_at = row.published_at or now
            row.hidden_at = None
        elif target == "hidden":
            row.hidden_at = now
        elif target == "deleted":
            row.deleted_at = now
            row.body = ""
            row.data = PostDataEnvelope(schema_version=row.schema_version, payload={})
        discussion.version += 1
        discussion.updated_at = now
        if row.number == 1 and target in {"hidden", "deleted"} and discussion.status == "published":
            discussion.status = "hidden"
            discussion.hidden_at = now
            await _emit(
                ctx,
                uow,
                "community.discussion_hidden.v1",
                discussion_id=str(discussion.id),
                status=discussion.status,
                version=discussion.version,
            )
        elif row.number == 1 and target == "published" and discussion.status == "hidden":
            discussion.status = "published"
            discussion.hidden_at = None
            discussion.published_at = discussion.published_at or now
            discussion_published = True
        await _recompute_summary(uow, discussion, changed_post=row)
        await uow.session.flush()
        await _sync_search_documents(uow, discussion, body_limit=spec.reply_body_max_bytes)
        if discussion_published:
            await _emit(
                ctx,
                uow,
                "community.discussion_published.v1",
                discussion_id=str(discussion.id),
                status=discussion.status,
                version=discussion.version,
            )
        event_key = {
            "published": "community.post_published.v1",
            "hidden": "community.post_hidden.v1",
            "deleted": "community.post_deleted.v1",
        }[target]
        await _emit(
            ctx,
            uow,
            event_key,
            discussion_id=str(discussion.id),
            post_id=str(row.id),
            status=row.status,
            version=row.version,
        )
        await _audit(
            ctx, uow, action=f"community.post.{action}", target_type="post", target_id=str(row.id)
        )
        await _commit(uow)
        return await _post_dto(ctx, row, spec)
    raise RuntimeError("community post transition did not execute")


def _validate_tag_display(input_: CreateTagInput | UpdateTagInput) -> None:
    if input_.name is not None and not input_.name.strip():
        raise _validation("community.invalid_tag_name", "tag name cannot be empty")
    if input_.color is not None and not _COLOR.fullmatch(input_.color):
        raise _validation(
            "community.tag_display_invalid", "color is not an allowed controlled value"
        )
    if input_.icon_key is not None and not _ICON_KEY.fullmatch(input_.icon_key):
        raise _validation(
            "community.tag_display_invalid", "icon_key is not an allowed controlled value"
        )


async def _validate_parent(
    uow: UnitOfWork,
    kind: str,
    parent_id: uuid.UUID | None,
    *,
    current_id: uuid.UUID | None = None,
) -> CommunityTag | None:
    if kind == "secondary" and parent_id is not None:
        raise _validation("community.tag_hierarchy_invalid", "secondary tags cannot have a parent")
    if parent_id is None:
        return None
    parent = await uow.session.get(CommunityTag, parent_id)
    if (
        parent is None
        or (current_id is not None and parent.id == current_id)
        or parent.status != "active"
        or parent.kind != "primary"
        or parent.parent_id is not None
    ):
        raise _validation(
            "community.tag_hierarchy_invalid", "parent must be an active root primary tag"
        )
    if kind != "primary":
        raise _validation("community.tag_hierarchy_invalid", "only primary tags can have children")
    return cast(CommunityTag, parent)


class CreateTag:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: CreateTagInput) -> TagDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_TAGS)
        if not _TAG_SLUG.fullmatch(input_.slug):
            raise _validation("community.invalid_tag_slug", "tag slug has an invalid format")
        _validate_tag_display(input_)
        now = _now(ctx)
        async with ctx.uow_factory() as uow:
            await _validate_parent(uow, input_.kind, input_.parent_id)
            row = CommunityTag(
                id=new_uuid7(),
                kind=input_.kind,
                parent_id=input_.parent_id,
                name=input_.name.strip(),
                slug=input_.slug,
                description=input_.description,
                color=input_.color,
                icon_key=input_.icon_key,
                position=0,
                status="active",
                metadata_=TagMetadataEnvelope(values=input_.metadata),
                version=1,
                created_at=now,
                updated_at=now,
            )
            uow.session.add(row)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                raise _conflict("community.tag_slug_conflict", "tag slug already exists") from exc
            await _emit(
                ctx,
                uow,
                "community.tag_created.v1",
                tag_id=str(row.id),
                kind=row.kind,
                version=row.version,
            )
            await _audit(
                ctx, uow, action="community.tag.create", target_type="tag", target_id=str(row.id)
            )
            await _commit(uow)
            return _tag_dto(row)
        raise RuntimeError("community tag creation did not execute")


class UpdateTag:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, tag_id: uuid.UUID, input_: UpdateTagInput) -> TagDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_TAGS)
        _validate_tag_display(input_)
        now = _now(ctx)
        async with ctx.uow_factory() as uow:
            row = await _get_tag(uow, tag_id)
            _check_version(row, input_.expected_version)
            changed = False
            for field in ("name", "description", "color", "icon_key"):
                value = getattr(input_, field)
                if value is not None and value != getattr(row, field):
                    setattr(row, field, value.strip() if isinstance(value, str) else value)
                    changed = True
            if "parent_id" in input_.model_fields_set and input_.parent_id != row.parent_id:
                await _validate_parent(uow, row.kind, input_.parent_id, current_id=row.id)
                row.parent_id = input_.parent_id
                changed = True
            if input_.metadata is not None:
                if input_.metadata != row.metadata_.values:
                    row.metadata_ = TagMetadataEnvelope(values=input_.metadata)
                    changed = True
            if not changed:
                raise _validation("community.empty_update", "nothing to update")
            row.version += 1
            row.updated_at = now
            await _emit(
                ctx,
                uow,
                "community.tag_updated.v1",
                tag_id=str(row.id),
                kind=row.kind,
                version=row.version,
            )
            await _audit(
                ctx, uow, action="community.tag.update", target_type="tag", target_id=str(row.id)
            )
            await _commit(uow)
            return _tag_dto(row)
        raise RuntimeError("community tag update did not execute")


class ArchiveTag:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, tag_id: uuid.UUID) -> TagDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_TAGS)
        now = _now(ctx)
        async with ctx.uow_factory() as uow:
            row = await _get_tag(uow, tag_id)
            if row.status == "archived":
                return _tag_dto(row)
            row.status = "archived"
            row.archived_at = now
            row.version += 1
            row.updated_at = now
            await _emit(
                ctx,
                uow,
                "community.tag_archived.v1",
                tag_id=str(row.id),
                kind=row.kind,
                version=row.version,
            )
            await _audit(
                ctx, uow, action="community.tag.archive", target_type="tag", target_id=str(row.id)
            )
            await _commit(uow)
            return _tag_dto(row)
        raise RuntimeError("community tag archive did not execute")


class RestoreTag:
    """Restore an archived tag without changing its stable identity."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, tag_id: uuid.UUID) -> TagDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_TAGS)
        now = _now(ctx)
        async with ctx.uow_factory() as uow:
            row = await _get_tag(uow, tag_id)
            if row.status == "active":
                return _tag_dto(row)
            row.status = "active"
            row.archived_at = None
            row.version += 1
            row.updated_at = now
            await _emit(
                ctx,
                uow,
                "community.tag_updated.v1",
                tag_id=str(row.id),
                kind=row.kind,
                version=row.version,
            )
            await _audit(
                ctx, uow, action="community.tag.restore", target_type="tag", target_id=str(row.id)
            )
            await _commit(uow)
            return _tag_dto(row)
        raise RuntimeError("community tag restore did not execute")


class ReorderTags:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: ReorderTagsInput) -> list[TagDTO]:
        ctx = self._ctx
        _require(ctx, PERMISSION_TAGS)
        if len(set(input_.tag_ids)) != len(input_.tag_ids):
            raise _validation(
                "community.tag_hierarchy_invalid", "duplicate tags cannot be reordered"
            )
        now = _now(ctx)
        async with ctx.uow_factory() as uow:
            rows = list(
                (
                    await uow.session.execute(
                        select(CommunityTag).where(CommunityTag.id.in_(input_.tag_ids))
                    )
                )
                .scalars()
                .all()
            )
            if len(rows) != len(input_.tag_ids):
                raise _validation("community.tag_not_found", "one or more tags do not exist")
            by_id = {row.id: row for row in rows}
            ordered = [by_id[tag_id] for tag_id in input_.tag_ids]
            first = ordered[0] if ordered else None
            if first is not None and any(
                row.kind != first.kind or row.parent_id != first.parent_id or row.status != "active"
                for row in ordered
            ):
                raise _validation(
                    "community.tag_hierarchy_invalid", "tags must share one active parent group"
                )
            for position, row in enumerate(ordered):
                row.position = position
                row.version += 1
                row.updated_at = now
                await _emit(
                    ctx,
                    uow,
                    "community.tag_updated.v1",
                    tag_id=str(row.id),
                    kind=row.kind,
                    version=row.version,
                )
            await _audit(
                ctx,
                uow,
                action="community.tag.reorder",
                target_type="tag",
                target_id=str(first.id) if first else "community",
            )
            await _commit(uow)
            return [_tag_dto(row) for row in ordered]
        raise RuntimeError("community tag reorder did not execute")


class RebuildCommunitySearch:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, *, dry_run: bool = False) -> dict[str, Any]:
        ctx = self._ctx
        _require(ctx, PERMISSION_SEARCH_REBUILD)
        async with ctx.uow_factory() as uow:
            discussions = list(
                (await uow.session.execute(select(CommunityDiscussion))).scalars().all()
            )
            before = int(
                (
                    await uow.session.execute(select(func.count(CommunitySearchDocument.id)))
                ).scalar_one()
            )
            if dry_run:
                expected = 0
                for row in discussions:
                    if row.status == "published":
                        expected += 1
                        expected += int(
                            (
                                await uow.session.execute(
                                    select(func.count(CommunityPost.id)).where(
                                        CommunityPost.discussion_id == row.id,
                                        CommunityPost.status == "published",
                                    )
                                )
                            ).scalar_one()
                        )
                return {
                    "dry_run": True,
                    "discussions": len(discussions),
                    "documents": before,
                    "expected_documents": expected,
                }
            for row in discussions:
                spec = _template(ctx, row.template_key)
                await _sync_search_documents(uow, row, body_limit=spec.body_max_bytes)
            await _audit(
                ctx,
                uow,
                action="community.search.rebuild",
                target_type="community",
                target_id="community",
                details={"discussions": len(discussions)},
            )
            await _commit(uow)
            after = int(
                (
                    await uow.session.execute(select(func.count(CommunitySearchDocument.id)))
                ).scalar_one()
            )
            return {
                "dry_run": False,
                "discussions": len(discussions),
                "documents_before": before,
                "documents_after": after,
            }
        raise RuntimeError("community search rebuild did not execute")


class PurgeArchivedDiscussions:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self, input_: PurgeArchivedDiscussionsInput | None = None, *, dry_run: bool | None = None
    ) -> dict[str, Any]:
        ctx = self._ctx
        _require(ctx, PERMISSION_PURGE)
        requested_dry_run = input_.dry_run if input_ is not None else bool(dry_run)
        async with ctx.uow_factory() as uow:
            rows = list(
                (
                    await uow.session.execute(
                        select(CommunityDiscussion).where(CommunityDiscussion.status == "archived")
                    )
                )
                .scalars()
                .all()
            )
            report = {
                "dry_run": requested_dry_run,
                "count": len(rows),
                "discussion_ids": [str(row.id) for row in rows],
            }
            if requested_dry_run:
                return report
            for row in rows:
                await uow.session.execute(
                    delete(CommunitySearchDocument).where(
                        CommunitySearchDocument.discussion_id == row.id
                    )
                )
                await uow.session.execute(
                    delete(CommunityDiscussionTag).where(
                        CommunityDiscussionTag.discussion_id == row.id
                    )
                )
                await uow.session.execute(
                    delete(CommunityPost).where(CommunityPost.discussion_id == row.id)
                )
                await uow.session.execute(
                    delete(CommunityDiscussion).where(CommunityDiscussion.id == row.id)
                )
            await _audit(
                ctx,
                uow,
                action="community.discussion.purge",
                target_type="community",
                target_id="community",
                details={"count": len(rows)},
            )
            await _commit(uow)
            return report
        raise RuntimeError("community discussion purge did not execute")
