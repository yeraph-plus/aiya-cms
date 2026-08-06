"""Authentication DTOs."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from inc.kernel.identity.models import UserStatus


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=64)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()


class AuthRegistrationPolicy(BaseModel):
    registration_open: bool = True
    default_role: Literal["reader", "member"] = "reader"


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=8, max_length=256)


class PasswordResetMailContext(BaseModel):
    reset_url: str
    expires_minutes: int


class PasswordResetDelivery(BaseModel):
    email: str
    token: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0)


class AuthMe(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: str
    display_name: str
    avatar_url: str | None = None
    status: UserStatus
    roles: frozenset[str] = frozenset()
    capabilities: frozenset[str] = frozenset()
