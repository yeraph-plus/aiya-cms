"""Identity DTOs.

Contract source: context/spec/capabilities/identity.md §5.

DTOs never carry password hashes or challenge digests; those stay inside
the capability.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SubjectDTO(BaseModel):
    """Public-facing subject reference."""

    model_config = ConfigDict(extra="forbid")

    id: str
    username: str
    display_name: str | None = None
    email: str
    email_verified: bool = False
    status: str = "active"
    avatar_asset_id: str | None = None
    created_at: datetime | None = None


class PublicProfileDTO(BaseModel):
    """Minimal public profile (deleted users get a minimal profile)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    username: str
    display_name: str | None = None
    avatar_asset_id: str | None = None
    deleted: bool = False


class ChallengeDTO(BaseModel):
    """Challenge metadata returned to the caller at issuance.

    ``token`` is the one-time opaque value shown exactly once at issuance
    (delivered out-of-band by the notification workflow); only its digest
    is ever stored.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    purpose: str
    expires_at: datetime
    attempts: int = 0
    max_attempts: int = 5
    token: str | None = Field(default=None, repr=False)


class RegistrationResult(BaseModel):
    """Result of RegisterLocalUser (no secrets)."""

    model_config = ConfigDict(extra="forbid")

    subject: SubjectDTO
    challenge: ChallengeDTO | None = None


class UpdateProfileInput(BaseModel):
    """Whitelisted profile fields; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=200)
    avatar_asset_id: str | None = None

    @field_validator("avatar_asset_id")
    @classmethod
    def _avatar_id(cls, value: str | None) -> str | None:
        if value is not None:
            import uuid

            uuid.UUID(value)
        return value
