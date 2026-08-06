"""Kernel comment application service, moderation and tree assembly."""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError

from inc.kernel.cache import Cache, cache_key
from inc.kernel.db import Page, UoWExecutor, integrity_to_app_error
from inc.kernel.errors import AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.rbac import RBAC_001, PolicyContext, check_capability
from inc.kernel.security import Principal

from .errors import COMMENT_001, COMMENT_002, COMMENT_003, COMMENT_004, COMMENT_005, COMMENT_006
from .events import COMMENT_EVENT_TYPES, CommentEventPayload, CommentModeratedPayload
from .models import Comment, CommentExtra, CommentStatus
from .schemas import (
    CommentCreate,
    CommentModerationQuery,
    CommentRead,
    CommentStats,
    CommentThread,
    CommentThreadQuery,
    CommentUpdate,
    ModerateAction,
)
from .targets import CommentTargetPolicy, TargetExists, TargetPolicyResolver
from .uow import CommentUnitOfWork


class CommentService:
    def __init__(
        self,
        executor: UoWExecutor[CommentUnitOfWork],
        cache: Cache,
        *,
        event_bus: EventBus | None = None,
        target_policy: TargetPolicyResolver,
        target_exists: TargetExists | None = None,
    ) -> None:
        self._executor = executor
        self._cache = cache
        self._event_bus = event_bus or get_event_bus()
        self._target_policy = target_policy
        self._target_exists = target_exists
        for event_type in COMMENT_EVENT_TYPES:
            if not self._event_bus.is_registered(event_type):
                self._event_bus.register(event_type)
        if self._event_bus.is_registered("content.deleted"):
            self._event_bus.subscribe("content.deleted", self._on_content_deleted)
        if self._event_bus.is_registered("user.banned"):
            self._event_bus.subscribe("user.banned", self._on_user_banned)

    async def list_threads(
        self,
        target_type: str,
        target_id: UUID,
        *,
        query: CommentThreadQuery,
        principal: Principal | None = None,
    ) -> Page[CommentThread]:
        target = self._require_target(target_type)
        self._ensure_allowed(target)
        if self._target_exists is not None and not await _maybe(
            self._target_exists(target_type, target_id)
        ):
            raise AppError(COMMENT_002)
        approved_only = not (
            principal is not None
            and (principal.is_system_bot or "comment:moderate" in principal.capabilities)
        )

        async def operation(uow: CommentUnitOfWork) -> Page[CommentThread]:
            total = await uow.comments.count_roots(
                target_type, target_id, approved_only=approved_only, q=query.q
            )
            roots = await uow.comments.list_roots(
                target_type,
                target_id,
                approved_only=approved_only,
                q=query.q,
                page=query.page,
                size=query.size,
                sort=query.sort,
                order=query.order,
            )
            descendants = await uow.comments.list_descendants(
                [root.id for root in roots], approved_only=approved_only
            )
            by_parent: dict[UUID, list[Comment]] = {}
            for row in descendants:
                if row.parent_id is not None:
                    by_parent.setdefault(row.parent_id, []).append(row)
            return Page(
                items=[self._thread(root, by_parent) for root in roots],
                total=total,
                page=query.page,
                size=query.size,
            )

        return await self._executor.read(operation)

    async def list_moderation(self, query: CommentModerationQuery) -> Page[CommentRead]:
        async def operation(uow: CommentUnitOfWork) -> Page[CommentRead]:
            page = await uow.comments.list_moderation(
                status=None if query.status is None else query.status.value,
                target_type=query.target_type,
                target_id=query.target_id,
                author_id=query.author_id,
                q=query.q,
                created_from=query.created_from,
                created_to=query.created_to,
                updated_from=query.updated_from,
                updated_to=query.updated_to,
                page=query.page,
                size=query.size,
                sort=query.sort,
                order=query.order,
            )
            return Page(
                items=[self._to_read(item) for item in page.items],
                total=page.total,
                page=page.page,
                size=page.size,
            )

        return await self._executor.read(operation)

    async def get(self, comment_id: UUID) -> CommentRead:
        async def operation(uow: CommentUnitOfWork) -> CommentRead:
            item = await uow.comments.get_or_none(comment_id)
            if item is None:
                raise AppError(COMMENT_001)
            return self._to_read(item)

        return await self._executor.read(operation)

    async def create(self, dto: CommentCreate, principal: Principal) -> CommentRead:
        self._require_capability(principal, "comment:create")
        target = self._require_target(dto.target_type)
        self._ensure_allowed(target)
        self._validate_target_data(target, dto.data)
        if self._target_exists is not None and not await _maybe(
            self._target_exists(dto.target_type, dto.target_id)
        ):
            raise AppError(COMMENT_002)
        key = cache_key("comment", "rl", str(principal.id), dto.target_type, str(dto.target_id))
        if await self._cache.increment(key, ttl=600) > target.rate_limit:
            raise AppError(COMMENT_004)

        async def operation(uow: CommentUnitOfWork) -> Comment:
            depth = 0
            root_id: UUID | None = None
            if dto.parent_id is not None:
                parent = await uow.comments.get_or_none(dto.parent_id)
                if (
                    parent is None
                    or parent.target_type != dto.target_type
                    or parent.target_id != dto.target_id
                ):
                    raise AppError(COMMENT_002)
                depth = parent.depth + 1
                if depth > target.max_depth:
                    raise AppError(COMMENT_003)
                root_id = parent.root_id or parent.id
            item = Comment(
                target_type=dto.target_type,
                target_id=dto.target_id,
                parent_id=dto.parent_id,
                root_id=root_id,
                depth=depth,
                owner_id=principal.id,
                status=(
                    CommentStatus.APPROVED.value
                    if target.auto_approve
                    else CommentStatus.PENDING.value
                ),
                content=dto.content,
                data=CommentExtra.model_validate(dto.data),
            )
            await uow.comments.add(item)
            return item

        try:
            item = await self._executor.write(operation)
        except IntegrityError as exc:
            raise integrity_to_app_error(exc) from exc
        counted = self._is_counted(item)
        self._publish(
            "comment.created",
            CommentEventPayload(
                comment_id=item.id,
                target_type=item.target_type,
                target_id=item.target_id,
                owner_id=item.owner_id,
                actor_id=principal.id,
                count_delta=1 if counted else 0,
            ),
            actor_id=principal.id,
        )
        return self._to_read(item)

    async def update(
        self, comment_id: UUID, dto: CommentUpdate, principal: Principal
    ) -> CommentRead:
        async def operation(uow: CommentUnitOfWork) -> Comment:
            item = await uow.comments.get_for_update_or_none(comment_id)
            if item is None:
                raise AppError(COMMENT_001)
            self._require_owner_or_moderator(principal, item.owner_id)
            target = self._require_target(item.target_type)
            if dto.data is not None:
                self._validate_target_data(target, dto.data)
            item.content = dto.content
            if dto.data is not None:
                item.data = CommentExtra.model_validate(dto.data).model_copy(
                    update={"edited": True}
                )
            else:
                item.data = item.data.model_copy(update={"edited": True})
            return item

        item = await self._executor.write(operation)
        self._publish(
            "comment.updated",
            CommentEventPayload(
                comment_id=item.id,
                target_type=item.target_type,
                target_id=item.target_id,
                owner_id=item.owner_id,
                actor_id=principal.id,
                changed_fields=("content", "data"),
            ),
            actor_id=principal.id,
        )
        return self._to_read(item)

    async def delete(self, comment_id: UUID, principal: Principal) -> None:
        async def operation(uow: CommentUnitOfWork) -> tuple[Comment, bool, int]:
            item = await uow.comments.get_for_update_or_none(comment_id)
            if item is None:
                raise AppError(COMMENT_001)
            self._require_delete(principal, item.owner_id)
            old_counted = self._is_counted(item)
            if await uow.comments.has_children(comment_id):
                item.content = "[deleted]"
                item.data = item.data.model_copy(update={"deleted": True})
                return item, False, -1 if old_counted else 0
            await uow.comments.delete(item)
            return item, True, -1 if old_counted else 0

        item, physical, count_delta = await self._executor.write(operation)
        self._publish(
            "comment.deleted",
            CommentEventPayload(
                comment_id=item.id,
                target_type=item.target_type,
                target_id=item.target_id,
                owner_id=item.owner_id,
                actor_id=principal.id,
                count_delta=count_delta,
                placeholder=not physical,
                physical=physical,
            ),
            actor_id=principal.id,
        )

    async def moderate(
        self, comment_id: UUID, action: ModerateAction, principal: Principal
    ) -> CommentRead:
        self._require_capability(principal, "comment:moderate")

        async def operation(uow: CommentUnitOfWork) -> tuple[Comment, int]:
            item = await uow.comments.get_for_update_or_none(comment_id)
            if item is None:
                raise AppError(COMMENT_001)
            allowed = {
                (CommentStatus.PENDING.value, "approve"),
                (CommentStatus.PENDING.value, "reject"),
                (CommentStatus.APPROVED.value, "reject"),
                (CommentStatus.PENDING.value, "spam"),
                (CommentStatus.APPROVED.value, "spam"),
                (CommentStatus.REJECTED.value, "spam"),
                (CommentStatus.SPAM.value, "spam"),
            }
            if (item.status, action) not in allowed:
                raise AppError(COMMENT_005)
            old_counted = self._is_counted(item)
            item.status = {
                "approve": CommentStatus.APPROVED.value,
                "reject": CommentStatus.REJECTED.value,
                "spam": CommentStatus.SPAM.value,
            }[action]
            return item, (1 if self._is_counted(item) else 0) - (1 if old_counted else 0)

        item, count_delta = await self._executor.write(operation)
        self._publish(
            "comment.moderated",
            CommentModeratedPayload(
                comment_id=item.id,
                target_type=item.target_type,
                target_id=item.target_id,
                owner_id=item.owner_id,
                action=action,
                actor_id=principal.id,
                count_delta=count_delta,
            ),
            actor_id=principal.id,
        )
        return self._to_read(item)

    async def stats_for_targets(
        self, target_type: str, target_ids: Sequence[UUID]
    ) -> dict[UUID, CommentStats]:
        target = self._require_target(target_type)
        self._ensure_allowed(target)

        async def operation(uow: CommentUnitOfWork) -> dict[UUID, CommentStats]:
            result: dict[UUID, CommentStats] = {}
            for target_id in target_ids:
                count = await uow.comments.count_for_target(
                    target_type, target_id, approved_only=True
                )
                result[target_id] = CommentStats(count=count)
            return result

        return await self._executor.read(operation)

    async def recount_target(self, target_type: str, target_id: UUID) -> int:
        target = self._require_target(target_type)
        self._ensure_allowed(target)

        async def operation(uow: CommentUnitOfWork) -> int:
            return await uow.comments.count_for_target(target_type, target_id, approved_only=True)

        return await self._executor.read(operation)

    async def purge_orphans(self, principal: Principal | None = None) -> int:
        actor = principal or Principal.system_bot()
        self._require_capability(actor, "comment:moderate")
        cutoff = datetime.now(UTC) - timedelta(days=30)
        return await self._executor.write(lambda uow: uow.comments.purge_orphans_before(cutoff))

    async def _on_content_deleted(self, event: Event) -> None:
        payload = event.payload
        target_type = getattr(payload, "type", None)
        target_id = getattr(payload, "content_id", None)
        if isinstance(target_type, str) and isinstance(target_id, UUID):
            await self._executor.write(
                lambda uow: uow.comments.mark_target_deleted(target_type, target_id)
            )

    async def _on_user_banned(self, event: Event) -> None:
        user_id = getattr(event.payload, "user_id", None)
        if isinstance(user_id, UUID):
            await self._executor.write(lambda uow: uow.comments.mark_pending_spam(user_id))

    def _require_target(self, target_type: str) -> CommentTargetPolicy:
        policy = self._target_policy(target_type)
        if policy is not None:
            return policy
        raise AppError(COMMENT_006)

    @staticmethod
    def _ensure_allowed(target: CommentTargetPolicy) -> None:
        if not target.allow:
            raise AppError(COMMENT_002)

    @staticmethod
    def _validate_target_data(target: CommentTargetPolicy, value: dict[str, Any]) -> None:
        if target.data_model is BaseModel:
            return
        try:
            target.data_model.model_validate(value)
        except ValidationError as exc:
            raise AppError(COMMENT_002, cause=exc) from exc

    @staticmethod
    def _thread(root: Comment, by_parent: dict[UUID, list[Comment]]) -> CommentThread:
        item = CommentThread(**CommentService._to_read(root).model_dump(), children=[])
        item.children = [
            CommentService._thread(child, by_parent) for child in by_parent.get(root.id, [])
        ]
        return item

    @staticmethod
    def _to_read(item: Comment) -> CommentRead:
        return CommentRead(
            id=item.id,
            target_type=item.target_type,
            target_id=item.target_id,
            parent_id=item.parent_id,
            root_id=item.root_id,
            depth=item.depth,
            owner_id=item.owner_id,
            status=CommentStatus(item.status),
            content=item.content,
            data=item.data.model_dump(mode="json"),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    @staticmethod
    def _is_counted(item: Comment) -> bool:
        return item.status == CommentStatus.APPROVED.value and not item.data.deleted

    @staticmethod
    def _require_capability(principal: Principal, alias: str) -> None:
        if not check_capability(principal, alias):
            raise AppError(RBAC_001, detail={"alias": alias})

    @staticmethod
    def _require_owner_or_moderator(principal: Principal, owner_id: UUID) -> None:
        if check_capability(principal, "comment:moderate"):
            return
        if not check_capability(
            principal, "comment:update_own", PolicyContext(resource_owner_id=owner_id)
        ):
            raise AppError(RBAC_001, detail={"alias": "comment:update_own"})

    @staticmethod
    def _require_delete(principal: Principal, owner_id: UUID) -> None:
        if check_capability(principal, "comment:delete_any"):
            return
        if not check_capability(
            principal, "comment:delete_own", PolicyContext(resource_owner_id=owner_id)
        ):
            raise AppError(RBAC_001, detail={"alias": "comment:delete_own"})

    def _publish(self, event_type: str, payload: Any, *, actor_id: UUID | None = None) -> None:
        self._event_bus.publish(Event(type=event_type, payload=payload, actor_id=actor_id))


async def _maybe(value: bool | Awaitable[bool]) -> bool:
    return await value if hasattr(value, "__await__") else value
