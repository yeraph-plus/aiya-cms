"""Kernel Content application service."""

from __future__ import annotations

from builtins import list as ListType
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from inc.kernel.db import Page, UoWExecutor
from inc.kernel.errors import COMMON_403, AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.rbac import PolicyContext, check_capability
from inc.kernel.security import Principal

from .definitions import ContentTypeDefinition
from .errors import CONTENT_001, CONTENT_002, CONTENT_003, CONTENT_004, CONTENT_005
from .events import CONTENT_EVENT_TYPES, ContentEventPayload
from .interpreter import ContentTypeInterpreter
from .models import Content
from .registry import ContentTypeRegistry
from .schemas import (
    ContentCreate,
    ContentDataValues,
    ContentListQuery,
    ContentRead,
    ContentTypeRead,
    ContentUpdate,
    TransitionAction,
)
from .uow import ContentUnitOfWork

TermFilterResolver = Callable[[str, str], Sequence[UUID] | Awaitable[Sequence[UUID]]]
CommentStatsResolver = Callable[[str, Sequence[UUID]], dict[UUID, int] | Awaitable[dict[UUID, int]]]


class ContentService:
    def __init__(
        self,
        executor: UoWExecutor[ContentUnitOfWork],
        *,
        event_bus: EventBus | None = None,
        registry: ContentTypeRegistry,
        term_filter: TermFilterResolver | None = None,
        comment_stats: CommentStatsResolver | None = None,
    ) -> None:
        self._executor = executor
        self._event_bus = event_bus or get_event_bus()
        self._registry = registry
        self._interpreter = ContentTypeInterpreter()
        self._term_filter = term_filter
        self._comment_stats = comment_stats
        for event_type in CONTENT_EVENT_TYPES:
            if not self._event_bus.is_registered(event_type):
                self._event_bus.register(event_type)
        for event_type in ("comment.created", "comment.deleted", "comment.moderated"):
            if self._event_bus.is_registered(event_type):
                self._event_bus.subscribe(event_type, self._on_comment_event)

    def set_term_filter(self, resolver: TermFilterResolver) -> None:
        self._term_filter = resolver

    def set_comment_stats(self, resolver: CommentStatsResolver) -> None:
        self._comment_stats = resolver

    async def list_types(self) -> list[ContentTypeRead]:
        result: list[ContentTypeRead] = []
        for type_name in self._registry.keys():
            definition = self._registry.require(type_name)
            metadata = definition.metadata()
            metadata["query"] = {
                "fields": ["page", "size", "q", "terms", "status", "owner_id"],
                "sort": [
                    "title",
                    "slug",
                    "status",
                    "published_at",
                    "created_at",
                    "updated_at",
                    "view_count",
                    "like_count",
                    "rating_sum",
                    "rating_count",
                    "comment_count",
                ],
                "order": ["asc", "desc"],
            }
            result.append(ContentTypeRead.model_validate(metadata))
        return result

    async def create(self, type_name: str, dto: ContentCreate, principal: Principal) -> ContentRead:
        self._require_capability(principal, "content:create")
        definition = self._require_type(type_name)
        data = self._validate_data(definition, dto.data)
        if not _valid_slug(dto.slug):
            raise AppError(CONTENT_005, detail={"field": "slug"})

        async def operation(uow: ContentUnitOfWork) -> Content:
            item = Content(
                type=type_name,
                title=dto.title,
                slug=dto.slug,
                owner_id=principal.id,
                status=definition.default_status,
                content=dto.content,
                excerpt=dto.excerpt,
                data=data,
            )
            if self._is_public(definition, item.status):
                item.published_at = datetime.now(UTC)
            await uow.contents.add(item)
            return item

        try:
            item = await self._executor.write(operation)
        except IntegrityError as exc:
            raise AppError(CONTENT_002) from exc
        self._publish(
            "content.created",
            ContentEventPayload(content_id=item.id, type=type_name, owner_id=item.owner_id),
        )
        return self._to_read(item)

    async def get_by_slug(
        self, type_name: str, slug: str, principal: Principal | None = None
    ) -> ContentRead:
        definition = self._require_type(type_name)
        subject = principal or Principal.anonymous()

        async def operation(uow: ContentUnitOfWork) -> Content:
            item = await uow.contents.get_by_type_slug(type_name, slug)
            if item is None or not self._visible(item, subject, definition):
                raise AppError(CONTENT_003)
            return item

        return self._to_read(await self._executor.read(operation))

    async def list(
        self,
        type_name: str,
        query: ContentListQuery,
        principal: Principal | None = None,
    ) -> Page[ContentRead]:
        definition = self._require_type(type_name)
        subject = principal or Principal.anonymous()
        statuses, owner_id = self._visibility(subject, definition)
        if query.status is not None:
            known_statuses = {status.slug for status in definition.statuses} | {"trash"}
            if query.status not in known_statuses:
                raise AppError(CONTENT_005, detail={"field": "status"})
            statuses = [query.status] if query.status in statuses else []
        if query.owner_id is not None:
            if owner_id is not None and owner_id != query.owner_id:
                statuses = []
            else:
                owner_id = query.owner_id

        content_ids: Sequence[UUID] | None = None
        if query.terms:
            if self._term_filter is None:
                raise AppError(CONTENT_005, detail={"field": "terms"})
            try:
                content_ids = await _maybe(self._term_filter(type_name, query.terms))
            except (ValueError, KeyError) as exc:
                raise AppError(CONTENT_005, detail={"field": "terms"}, cause=exc) from exc

        async def operation(uow: ContentUnitOfWork) -> Page[ContentRead]:
            page = await uow.contents.list_for_type(
                type_name,
                statuses=statuses,
                content_ids=content_ids,
                owner_id=owner_id,
                page=query.page,
                size=query.size,
                sort=query.sort,
                order=query.order,
                q=query.q,
                created_from=query.created_from,
                created_to=query.created_to,
                updated_from=query.updated_from,
                updated_to=query.updated_to,
                published_from=query.published_from,
                published_to=query.published_to,
            )
            return Page(
                items=[self._to_read(item) for item in page.items],
                total=page.total,
                page=page.page,
                size=page.size,
            )

        return await self._executor.read(operation)

    async def exists(self, type_name: str, content_id: UUID) -> bool:
        self._require_type(type_name)

        async def operation(uow: ContentUnitOfWork) -> bool:
            item = await uow.contents.get_or_none(content_id)
            return item is not None and item.type == type_name

        return await self._executor.read(operation)

    async def update(
        self, type_name: str, content_id: UUID, dto: ContentUpdate, principal: Principal
    ) -> ContentRead:
        definition = self._require_type(type_name)
        managed_fields = dto.model_fields_set.intersection({"comment_count", "trashed_at"})
        if managed_fields:
            raise AppError(
                CONTENT_005,
                detail={"fields": sorted(managed_fields), "reason": "system_managed"},
            )

        async def operation(uow: ContentUnitOfWork) -> tuple[Content, tuple[str, ...]]:
            item = await uow.contents.get_for_update_or_none(content_id)
            if item is None or item.type != type_name:
                raise AppError(CONTENT_003)
            self._require_owner_or_any(principal, "content:update", item.owner_id)
            changed: list[str] = []
            if dto.title is not None:
                item.title = dto.title
                changed.append("title")
            if dto.slug is not None:
                if not _valid_slug(dto.slug):
                    raise AppError(CONTENT_005, detail={"field": "slug"})
                item.slug = dto.slug
                changed.append("slug")
            if dto.content is not None:
                item.content = dto.content
                changed.append("content")
            if dto.excerpt is not None:
                item.excerpt = dto.excerpt
                changed.append("excerpt")
            if dto.data is not None:
                item.data = self._validate_data(definition, dto.data)
                changed.append("data")
            return item, tuple(changed)

        try:
            item, changed = await self._executor.write(operation)
        except IntegrityError as exc:
            raise AppError(CONTENT_002) from exc
        self._publish(
            "content.updated",
            ContentEventPayload(
                content_id=item.id, type=item.type, owner_id=item.owner_id, changed_fields=changed
            ),
            actor_id=principal.id,
        )
        return self._to_read(item)

    async def transition(
        self, type_name: str, content_id: UUID, action: TransitionAction, principal: Principal
    ) -> ContentRead:
        definition = self._require_type(type_name)

        async def operation(uow: ContentUnitOfWork) -> tuple[Content, bool, str | None]:
            item = await uow.contents.get_for_update_or_none(content_id)
            if item is None or item.type != type_name:
                raise AppError(CONTENT_003)
            if action == "purge":
                self._require_capability(principal, "content:delete_any")
                await uow.contents.delete(item)
                return item, True, None
            if action == "trash":
                self._require_owner_or_any(principal, "content:delete", item.owner_id)
                if item.status == "trash":
                    raise AppError(CONTENT_004)
                item.status = "trash"
                item.trashed_at = datetime.now(UTC)
                item.published_at = None
                return item, False, "content.trashed"
            if action == "restore":
                self._require_owner_or_any(principal, "content:update", item.owner_id)
                if item.status != "trash":
                    raise AppError(CONTENT_004)
                item.status = definition.default_status
                item.trashed_at = None
                item.published_at = (
                    datetime.now(UTC) if self._is_public(definition, item.status) else None
                )
                return item, False, "content.restored"

            transition = next(
                (
                    transition
                    for transition in definition.transitions
                    if transition.action == action and item.status in transition.from_statuses
                ),
                None,
            )
            if transition is None:
                raise AppError(CONTENT_004)
            self._require_owner_or_any(principal, transition.capability, item.owner_id)
            item.status = transition.to_status
            item.published_at = (
                datetime.now(UTC) if self._is_public(definition, item.status) else None
            )
            return (
                item,
                False,
                "content.published"
                if self._is_public(definition, item.status)
                else "content.updated",
            )

        item, purged, event_type = await self._executor.write(operation)
        if purged:
            self._publish(
                "content.deleted",
                ContentEventPayload(
                    content_id=item.id, type=item.type, owner_id=item.owner_id, purged=True
                ),
                actor_id=principal.id,
            )
        elif event_type is not None:
            self._publish(
                event_type,
                ContentEventPayload(
                    content_id=item.id,
                    type=item.type,
                    owner_id=item.owner_id,
                    action=action,
                ),
                actor_id=principal.id,
            )
        return self._to_read(item)

    async def purge_trash(self, principal: Principal | None = None) -> int:
        actor = principal or Principal.system_bot()
        self._require_capability(actor, "content:delete_any")
        cutoff = datetime.now(UTC) - timedelta(days=30)

        async def operation(uow: ContentUnitOfWork) -> list[Content]:
            return await uow.contents.purge_trash_before(cutoff)

        items = await self._executor.write(operation)
        for item in items:
            self._publish(
                "content.deleted",
                ContentEventPayload(
                    content_id=item.id, type=item.type, owner_id=item.owner_id, purged=True
                ),
                actor_id=actor.id,
            )
        return len(items)

    async def recount_comments(self, principal: Principal | None = None) -> int:
        actor = principal or Principal.system_bot()
        self._require_capability(actor, "content:update_any")
        comment_stats = self._comment_stats
        if comment_stats is None:
            return 0

        async def operation(uow: ContentUnitOfWork) -> int:
            by_type = await uow.contents.list_ids_by_type()
            changed = 0
            for content_type, content_ids in by_type.items():
                counts = await _maybe_mapping(comment_stats(content_type, content_ids))
                for content_id in content_ids:
                    await uow.contents.set_comment_count(
                        content_type, content_id, counts.get(content_id, 0)
                    )
                    changed += 1
            return changed

        return await self._executor.write(operation)

    async def apply_interaction_change(
        self,
        content_id: UUID,
        *,
        kind: str,
        numeric_value: int | None,
        previous_value: int | None,
        existed: bool,
        deleted: bool = False,
    ) -> None:
        like_delta = 0
        rating_sum_delta = 0
        rating_count_delta = 0
        if kind == "like":
            like_delta = -1 if deleted and existed else 1 if not existed else 0
        elif kind == "rating":
            if deleted and existed:
                rating_sum_delta = -(previous_value or 0)
                rating_count_delta = -1
            elif not existed:
                rating_sum_delta = numeric_value or 0
                rating_count_delta = 1
            else:
                rating_sum_delta = (numeric_value or 0) - (previous_value or 0)

        async def operation(uow: ContentUnitOfWork) -> None:
            await uow.contents.apply_interaction_delta(
                content_id,
                like_delta=like_delta,
                rating_sum_delta=rating_sum_delta,
                rating_count_delta=rating_count_delta,
            )

        await self._executor.write(operation)

    async def apply_comment_count_change(
        self, content_type: str, content_id: UUID, delta: int
    ) -> None:
        if delta == 0:
            return

        async def operation(uow: ContentUnitOfWork) -> None:
            await uow.contents.apply_comment_count_delta(
                content_id, delta, content_type=content_type
            )

        await self._executor.write(operation)

    async def _on_comment_event(self, event: Event) -> None:
        payload = event.payload
        content_type = getattr(payload, "target_type", None)
        content_id = getattr(payload, "target_id", None)
        delta = getattr(payload, "count_delta", 0)
        if (
            isinstance(content_type, str)
            and isinstance(content_id, UUID)
            and isinstance(delta, int)
        ):
            await self.apply_comment_count_change(content_type, content_id, delta)

    def _require_type(self, type_name: str) -> ContentTypeDefinition:
        try:
            return self._registry.require(type_name)
        except KeyError as exc:
            raise AppError(CONTENT_001, detail={"type": type_name}) from exc

    def _validate_data(self, definition: ContentTypeDefinition, value: Any) -> ContentDataValues:
        try:
            return self._interpreter.validate_data(definition, value)
        except (TypeError, ValueError) as exc:
            raise AppError(CONTENT_005, cause=exc) from exc

    @staticmethod
    def _to_read(item: Content) -> ContentRead:
        return ContentRead(
            id=item.id,
            type=item.type,
            title=item.title,
            slug=item.slug,
            status=item.status,
            owner_id=item.owner_id,
            content=item.content,
            excerpt=item.excerpt,
            view_count=item.view_count or 0,
            like_count=item.like_count or 0,
            rating_sum=item.rating_sum or 0,
            rating_count=item.rating_count or 0,
            comment_count=item.comment_count or 0,
            data=item.data.model_dump(mode="json"),
            published_at=item.published_at,
            trashed_at=item.trashed_at,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    @staticmethod
    def _visible(item: Content, principal: Principal, definition: ContentTypeDefinition) -> bool:
        if ContentService._is_public(definition, item.status):
            return True
        return check_capability(principal, "content:update_any") or (
            item.owner_id == principal.id
            and check_capability(
                principal, "content:update_own", PolicyContext(resource_owner_id=item.owner_id)
            )
        )

    @staticmethod
    def _visibility(
        principal: Principal, definition: ContentTypeDefinition
    ) -> tuple[ListType[str], UUID | None]:
        public = [status.slug for status in definition.statuses if status.is_public]
        if check_capability(principal, "content:update_any"):
            return [*public, *[status.slug for status in definition.statuses], "trash"], None
        if not principal.is_anonymous:
            return list(dict.fromkeys([*public, definition.default_status])), principal.id
        return public, None

    @staticmethod
    def _is_public(definition: ContentTypeDefinition, status: str) -> bool:
        return any(item.slug == status and item.is_public for item in definition.statuses)

    @staticmethod
    def _require_capability(principal: Principal, alias: str) -> None:
        if not check_capability(principal, alias):
            raise AppError(COMMON_403, detail={"alias": alias})

    @staticmethod
    def _require_owner_or_any(principal: Principal, operation: str, owner_id: UUID) -> None:
        if operation == "content:publish":
            allowed = check_capability(
                principal, operation, PolicyContext(resource_owner_id=owner_id)
            ) or check_capability(principal, "content:update_any")
        else:
            base = operation.split(":", 1)[1]
            allowed = check_capability(
                principal,
                f"content:{base}_own",
                PolicyContext(resource_owner_id=owner_id),
            ) or check_capability(principal, f"content:{base}_any")
        if not allowed:
            raise AppError(COMMON_403, detail={"alias": operation})

    def _publish(self, event_type: str, payload: Any, *, actor_id: UUID | None = None) -> None:
        self._event_bus.publish(Event(type=event_type, payload=payload, actor_id=actor_id))


def _valid_slug(value: str) -> bool:
    import re

    return re.fullmatch(r"^[a-z0-9][a-z0-9-]*$", value) is not None


async def _maybe(value: Sequence[UUID] | Awaitable[Sequence[UUID]]) -> Sequence[UUID]:
    return await value if hasattr(value, "__await__") else value


async def _maybe_mapping(
    value: dict[UUID, int] | Awaitable[dict[UUID, int]],
) -> dict[UUID, int]:
    return await value if hasattr(value, "__await__") else value
