"""Interaction commands and current-user history."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from inc.kernel.db import Page, UoWExecutor, integrity_to_app_error
from inc.kernel.errors import COMMON_404, COMMON_500, AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.security import Principal

from .models import Interaction, InteractionKind
from .schemas import InteractionChangedPayload, InteractionQuery, InteractionRead, RatingWrite
from .uow import InteractionUnitOfWork

TargetExists = Callable[[str, UUID], bool | Awaitable[bool]]
InteractionKindValue = Literal["like", "rating"]


class InteractionService:
    def __init__(
        self,
        executor: UoWExecutor[InteractionUnitOfWork],
        *,
        target_exists: TargetExists | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._executor = executor
        self._target_exists = target_exists
        self._event_bus = event_bus or get_event_bus()
        if not self._event_bus.is_registered("interaction.changed"):
            self._event_bus.register("interaction.changed")

    def set_target_exists(self, resolver: TargetExists) -> None:
        self._target_exists = resolver

    async def like(self, target_id: UUID, principal: Principal) -> InteractionRead:
        return await self._upsert(target_id, InteractionKind.LIKE.value, None, principal)

    async def unlike(self, target_id: UUID, principal: Principal) -> None:
        await self._delete(target_id, InteractionKind.LIKE.value, principal)

    async def rate(
        self, target_id: UUID, payload: RatingWrite, principal: Principal
    ) -> InteractionRead:
        return await self._upsert(target_id, InteractionKind.RATING.value, payload.score, principal)

    async def unrate(self, target_id: UUID, principal: Principal) -> None:
        await self._delete(target_id, InteractionKind.RATING.value, principal)

    async def history(self, query: InteractionQuery, principal: Principal) -> Page[InteractionRead]:
        async def operation(uow: InteractionUnitOfWork) -> Page[InteractionRead]:
            page = await uow.interactions.list_for_user(
                principal.id, kind=query.kind, page=query.page, size=query.size
            )
            return Page(
                items=[InteractionRead.model_validate(item) for item in page.items],
                total=page.total,
                page=page.page,
                size=page.size,
            )

        return await self._executor.read(operation)

    async def _upsert(
        self,
        target_id: UUID,
        kind: InteractionKindValue,
        numeric_value: int | None,
        principal: Principal,
    ) -> InteractionRead:
        await self._ensure_target(target_id)

        async def operation(uow: InteractionUnitOfWork) -> tuple[Interaction, bool, int | None]:
            item = await uow.interactions.get_for_update_by_identity(
                principal.id, "content", target_id, kind
            )
            existed = item is not None
            previous_value = None if item is None else item.numeric_value
            if item is None:
                item = Interaction(
                    user_id=principal.id,
                    target_type="content",
                    target_id=target_id,
                    kind=kind,
                    numeric_value=numeric_value,
                )
                await uow.interactions.add(item)
            else:
                item.numeric_value = numeric_value
            return item, existed, previous_value

        try:
            item, existed, previous_value = await self._executor.write(operation)
        except IntegrityError as exc:
            raise integrity_to_app_error(exc) from exc
        result = InteractionRead.model_validate(item)
        self._event_bus.publish(
            Event(
                type="interaction.changed",
                payload=InteractionChangedPayload(
                    user_id=principal.id,
                    target_type="content",
                    target_id=target_id,
                    kind=kind,
                    numeric_value=numeric_value,
                    existed=existed,
                    previous_value=previous_value,
                ),
                actor_id=principal.id,
            )
        )
        return result

    async def _delete(
        self, target_id: UUID, kind: InteractionKindValue, principal: Principal
    ) -> None:
        await self._ensure_target(target_id)

        async def operation(uow: InteractionUnitOfWork) -> Interaction | None:
            item = await uow.interactions.get_for_update_by_identity(
                principal.id, "content", target_id, kind
            )
            if item is not None:
                await uow.interactions.delete(item)
            return item

        item = await self._executor.write(operation)
        self._event_bus.publish(
            Event(
                type="interaction.changed",
                payload=InteractionChangedPayload(
                    user_id=principal.id,
                    target_type="content",
                    target_id=target_id,
                    kind=kind,
                    deleted=item is not None,
                    existed=item is not None,
                    previous_value=None if item is None else item.numeric_value,
                ),
                actor_id=principal.id,
            )
        )

    async def _ensure_target(self, target_id: UUID) -> None:
        if self._target_exists is None:
            raise AppError(
                COMMON_500, detail={"reason": "interaction target resolver is not wired"}
            )
        exists = self._target_exists("post", target_id)
        if isawaitable(exists):
            exists = await exists
        if not exists:
            raise AppError(COMMON_404)
