"""Identity DTOs crossing the module boundary.

Consumers (api, modules) touch only these, never the ORM models.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import UserStatus

_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    email: str = Field(min_length=3, max_length=320, pattern=_EMAIL_PATTERN)
    display_name: str = Field(min_length=1, max_length=64)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    display_name: str
    avatar_url: str | None = None
    status: UserStatus


class UserQuery(BaseModel):
    q: str | None = Field(default=None, max_length=128)
    status: UserStatus | None = None
    role: str | None = Field(default=None, max_length=32)
    created_from: datetime | None = None
    created_to: datetime | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
    sort: Literal["username", "email", "display_name", "status", "created_at", "updated_at"] = (
        "created_at"
    )
    order: Literal["asc", "desc"] = "desc"


class UserAdminUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    avatar_url: str | None = Field(default=None, max_length=512)


class UserAdminRead(UserRead):
    created_at: datetime
    updated_at: datetime
    roles: list[str] = Field(default_factory=list)


class UserRoleSet(BaseModel):
    roles: list[str] = Field(min_length=1, max_length=8)
