"""Identity service: user CRUD and the status state machine.

Consumers depend on this service (via UserRead DTOs), never on the ORM models.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from inc.kernel.db import Page, UoWExecutor, integrity_to_app_error, new_uuid7
from inc.kernel.errors import COMMON_409, AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.security import Principal

from .errors import USER_001, USER_002
from .events import IDENTITY_EVENT_TYPES, UserStatusChangedPayload
from .models import User, UserStatus
from .schemas import UserAdminUpdate, UserCreate, UserQuery, UserRead
from .uow import IdentityUnitOfWork


def _anon_token() -> str:
    # username is VARCHAR(32); "deleted-" leaves 24 chars for the unique token
    return new_uuid7().hex[:24]


_TRANSITIONS: dict[UserStatus, frozenset[UserStatus]] = {
    UserStatus.ACTIVE: frozenset({UserStatus.BANNED, UserStatus.DELETED}),
    UserStatus.BANNED: frozenset({UserStatus.ACTIVE, UserStatus.DELETED}),
    UserStatus.DELETED: frozenset(),
}


class IdentityService:
    """Application service for the identity component (no session access)."""

    def __init__(
        self,
        executor: UoWExecutor[IdentityUnitOfWork],
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        self._executor = executor
        self._event_bus = event_bus or get_event_bus()
        for event_type in IDENTITY_EVENT_TYPES:
            if not self._event_bus.is_registered(event_type):
                self._event_bus.register(event_type)

    async def create_user(self, dto: UserCreate) -> UserRead:
        async def operation(uow: IdentityUnitOfWork) -> User:
            user = User(
                username=dto.username,
                email=dto.email,
                display_name=dto.display_name,
            )
            await uow.users.add(user)
            return user

        try:
            return UserRead.model_validate(await self._executor.write(operation))
        except IntegrityError as exc:
            raise integrity_to_app_error(exc) from exc

    async def get_user(self, user_id: UUID) -> UserRead:
        async def operation(uow: IdentityUnitOfWork) -> UserRead:
            user = await self._require_user(uow, user_id)
            return UserRead.model_validate(user)

        return await self._executor.read(operation)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRead]:
        async def operation(uow: IdentityUnitOfWork) -> dict[UUID, UserRead]:
            rows = await uow.users.list_by_ids(user_ids)
            return {user.id: UserRead.model_validate(user) for user in rows}

        return await self._executor.read(operation)

    async def list_users(self, query: UserQuery) -> Page[UserRead]:
        async def operation(uow: IdentityUnitOfWork) -> Page[UserRead]:
            result = await uow.users.list_filtered(
                q=query.q,
                status=None if query.status is None else query.status.value,
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
                items=[UserRead.model_validate(item) for item in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )

        return await self._executor.read(operation)

    async def update(self, user_id: UUID, dto: UserAdminUpdate) -> UserRead:
        async def operation(uow: IdentityUnitOfWork) -> User:
            user = await self._require_user(uow, user_id, for_update=True)
            if dto.display_name is not None:
                user.display_name = dto.display_name
            if "avatar_url" in dto.model_fields_set:
                user.avatar_url = dto.avatar_url
            return user

        return UserRead.model_validate(await self._executor.write(operation))

    async def ban(self, user_id: UUID, actor: Principal | None = None) -> UserRead:
        if actor is not None and actor.id == user_id:
            raise AppError(USER_002)
        result = await self._transition(user_id, UserStatus.BANNED)
        self._publish_status("user.banned", result.id, actor)
        return result

    async def unban(self, user_id: UUID, actor: Principal | None = None) -> UserRead:
        result = await self._transition(user_id, UserStatus.ACTIVE)
        self._publish_status("user.unbanned", result.id, actor)
        return result

    async def delete(self, user_id: UUID, actor: Principal | None = None) -> UserRead:
        async def operation(uow: IdentityUnitOfWork) -> User:
            user = await self._require_user(uow, user_id, for_update=True)
            self._assert_transition(user, UserStatus.DELETED)
            token = _anon_token()
            user.username = f"deleted-{token}"
            user.email = f"deleted-{token}@invalid.local"
            user.status = UserStatus.DELETED.value
            for identity in await uow.identities.list_for_user(user.id):
                identity.provider_uid = f"deleted-{identity.id.hex}"
                identity.secret_hash = None
                identity.verified = False
            return user

        try:
            result = UserRead.model_validate(await self._executor.write(operation))
            self._publish_status("user.deleted", result.id, actor)
            return result
        except IntegrityError as exc:
            raise integrity_to_app_error(exc) from exc

    async def _transition(self, user_id: UUID, target: UserStatus) -> UserRead:
        async def operation(uow: IdentityUnitOfWork) -> User:
            user = await self._require_user(uow, user_id, for_update=True)
            self._assert_transition(user, target)
            user.status = target.value
            return user

        try:
            return UserRead.model_validate(await self._executor.write(operation))
        except IntegrityError as exc:
            raise integrity_to_app_error(exc) from exc

    async def _require_user(
        self,
        uow: IdentityUnitOfWork,
        user_id: UUID,
        *,
        for_update: bool = False,
    ) -> User:
        if for_update:
            user = await uow.users.get_for_update_or_none(user_id)
        else:
            user = await uow.users.get_or_none(user_id)
        if user is None:
            raise AppError(USER_001)
        return user

    def _assert_transition(self, user: User, target: UserStatus) -> None:
        current = UserStatus(user.status)
        if target not in _TRANSITIONS[current]:
            raise AppError(COMMON_409)

    def _publish_status(self, event_type: str, user_id: UUID, actor: Principal | None) -> None:
        actor_id = actor.id if actor is not None else UUID(int=0)
        self._event_bus.publish(
            Event(
                type=event_type,
                payload=UserStatusChangedPayload(user_id=user_id, actor_id=actor_id),
            )
        )
