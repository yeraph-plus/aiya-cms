"""Registered authentication domain events and payload DTOs."""

from uuid import UUID

from pydantic import BaseModel

AUTH_EVENT_TYPES: tuple[str, ...] = (
    "user.registered",
    "user.login_succeeded",
    "user.login_failed",
    "user.password_changed",
)


class UserRegisteredPayload(BaseModel):
    user_id: UUID


class UserLoginSucceededPayload(BaseModel):
    user_id: UUID
    ip: str


class UserLoginFailedPayload(BaseModel):
    identifier: str
    ip: str
    reason: str


class UserPasswordChangedPayload(BaseModel):
    user_id: UUID
