"""RBAC domain events."""

from uuid import UUID

from pydantic import BaseModel

RBAC_EVENT_TYPES: tuple[str, ...] = ("role.assigned", "role.membership_replaced")


class RoleAssignedPayload(BaseModel):
    user_id: UUID
    role: str
    actor_id: UUID


class RoleMembershipReplacedPayload(BaseModel):
    user_id: UUID
    roles: tuple[str, ...]
    actor_id: UUID
