"""RBAC application service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from inc.kernel.db import Page, UoWExecutor, integrity_to_app_error
from inc.kernel.errors import AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.identity.errors import USER_001
from inc.kernel.identity.models import UserStatus
from inc.kernel.identity.schemas import UserAdminRead, UserQuery, UserRead
from inc.kernel.security import Principal

from .errors import RBAC_002, RBAC_004
from .events import RBAC_EVENT_TYPES, RoleAssignedPayload, RoleMembershipReplacedPayload
from .schemas import PermissionRead, RoleAssign, RoleRead, UserRoleSet
from .uow import RBACUnitOfWork


class RBACService:
    def __init__(
        self,
        executor: UoWExecutor[RBACUnitOfWork],
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        self._executor = executor
        self._event_bus = event_bus or get_event_bus()
        for event_type in RBAC_EVENT_TYPES:
            if not self._event_bus.is_registered(event_type):
                self._event_bus.register(event_type)

    async def list_roles(self) -> list[RoleRead]:
        async def operation(uow: RBACUnitOfWork) -> list[RoleRead]:
            return [
                RoleRead(
                    id=item.id,
                    name=item.name,
                    description=item.description,
                    permissions=[permission.alias for permission in item.permissions],
                )
                for item in await uow.roles.list_ordered()
            ]

        return await self._executor.read(operation)

    async def list_permissions(self) -> list[PermissionRead]:
        async def operation(uow: RBACUnitOfWork) -> list[PermissionRead]:
            return [
                PermissionRead.model_validate(item) for item in await uow.permissions.list_ordered()
            ]

        return await self._executor.read(operation)

    async def assign_role(
        self,
        user_id: UUID,
        dto: RoleAssign,
        *,
        actor: Principal,
    ) -> UserRead:
        if user_id == actor.id:
            raise AppError(RBAC_004)

        async def operation(uow: RBACUnitOfWork) -> tuple[UserRead, str]:
            user = await uow.users.get_or_none(user_id)
            if user is None:
                raise AppError(USER_001)
            role = await uow.roles.get_by_name(dto.role)
            if role is None:
                raise AppError(RBAC_002, detail={"role": dto.role})
            await uow.rbac.assign_role(user.id, role.id, dto.organization_id)
            return UserRead.model_validate(user), role.name

        try:
            result, role_name = await self._executor.write(operation)
        except IntegrityError as exc:
            raise integrity_to_app_error(exc) from exc
        self._event_bus.publish(
            Event(
                type="role.assigned",
                payload=RoleAssignedPayload(user_id=user_id, role=role_name, actor_id=actor.id),
                actor_id=actor.id,
            )
        )
        return result

    async def replace_roles(
        self,
        user_id: UUID,
        dto: UserRoleSet,
        *,
        actor: Principal,
    ) -> UserAdminRead:
        if user_id == actor.id:
            raise AppError(RBAC_004)

        async def operation(uow: RBACUnitOfWork) -> tuple[UserAdminRead, list[str]]:
            user = await uow.users.get_for_update_or_none(user_id)
            if user is None:
                raise AppError(USER_001)
            role_ids = []
            role_names: list[str] = []
            for role_name in dto.roles:
                role = await uow.roles.get_by_name(role_name)
                if role is None:
                    raise AppError(RBAC_002, detail={"role": role_name})
                role_ids.append(role.id)
                role_names.append(role.name)
            await uow.rbac.replace_roles(user.id, role_ids)
            return (
                UserAdminRead(
                    id=user.id,
                    username=user.username,
                    email=user.email,
                    display_name=user.display_name,
                    avatar_url=user.avatar_url,
                    status=UserStatus(user.status),
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                    roles=role_names,
                ),
                role_names,
            )

        result, role_names = await self._executor.write(operation)
        self._event_bus.publish(
            Event(
                type="role.membership_replaced",
                payload=RoleMembershipReplacedPayload(
                    user_id=user_id,
                    roles=tuple(role_names),
                    actor_id=actor.id,
                ),
                actor_id=actor.id,
            )
        )
        return result

    async def get_user(self, user_id: UUID) -> UserAdminRead:
        async def operation(uow: RBACUnitOfWork) -> UserAdminRead:
            user = await uow.users.get_or_none(user_id)
            if user is None:
                raise AppError(USER_001)
            roles = await uow.rbac.role_names_for_user(user.id)
            return UserAdminRead(
                id=user.id,
                username=user.username,
                email=user.email,
                display_name=user.display_name,
                avatar_url=user.avatar_url,
                status=UserStatus(user.status),
                created_at=user.created_at,
                updated_at=user.updated_at,
                roles=sorted(roles),
            )

        return await self._executor.read(operation)

    async def list_users(self, query: UserQuery) -> Page[UserAdminRead]:
        async def operation(uow: RBACUnitOfWork) -> Page[UserAdminRead]:
            users = await uow.rbac.list_users_filtered(
                q=query.q,
                status=None if query.status is None else query.status.value,
                role=query.role,
                created_from=query.created_from,
                created_to=query.created_to,
                updated_from=query.updated_from,
                updated_to=query.updated_to,
                page=query.page,
                size=query.size,
                sort=query.sort,
                order=query.order,
            )
            role_map = await uow.rbac.role_names_for_users([user.id for user in users.items])
            return Page(
                items=[
                    UserAdminRead(
                        id=user.id,
                        username=user.username,
                        email=user.email,
                        display_name=user.display_name,
                        avatar_url=user.avatar_url,
                        status=UserStatus(user.status),
                        created_at=user.created_at,
                        updated_at=user.updated_at,
                        roles=sorted(role_map.get(user.id, frozenset())),
                    )
                    for user in users.items
                ],
                total=users.total,
                page=users.page,
                size=users.size,
            )

        return await self._executor.read(operation)

    async def build_principal(self, user_id: UUID) -> Principal:
        async def operation(uow: RBACUnitOfWork) -> Principal:
            user = await uow.users.get_or_none(user_id)
            if user is None:
                raise AppError(USER_001)
            return Principal(
                id=user.id,
                username=user.username,
                roles=await uow.rbac.role_names_for_user(user.id),
                capabilities=await uow.rbac.capabilities_for_user(user.id),
            )

        return await self._executor.read(operation)
