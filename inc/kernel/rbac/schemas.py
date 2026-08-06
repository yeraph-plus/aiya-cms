"""RBAC DTOs crossing the kernel boundary."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PolicyContext(BaseModel):
    """Generic context passed to resource-aware policies."""

    resource_owner_id: UUID | None = None
    target: dict[str, str] | None = None


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)


class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alias: str
    description: str | None = None


class RoleAssign(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    organization_id: UUID | None = None


class UserRoleSet(BaseModel):
    roles: list[str] = Field(min_length=1, max_length=8)
