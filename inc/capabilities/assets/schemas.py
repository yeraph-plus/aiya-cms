"""Assets DTOs and command inputs.

Contract source: context/spec/capabilities/assets.md §2/§5.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validated_checksum(value: str | None) -> str | None:
    if value is not None and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("checksum_sha256 must be 64 lowercase hex characters")
    return value


class AssetRefDTO(BaseModel):
    """Stable object reference; never carries a signed URL."""

    model_config = ConfigDict(extra="forbid")

    id: str
    provider_key: str
    bucket: str | None = None
    object_key: str
    mime_type: str
    byte_size: int
    checksum_sha256: str | None = None
    alt_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    state: str
    created_at: datetime
    updated_at: datetime

    @field_validator("checksum_sha256")
    @classmethod
    def _checksum(cls, value: str | None) -> str | None:
        return _validated_checksum(value)


class CreateUploadIntentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_key: str
    mime_types: tuple[str, ...] = Field(min_length=1)
    content_length_max: int = Field(gt=0, le=100 * 1024 * 1024)
    checksum_sha256: str | None = None

    @field_validator("checksum_sha256")
    @classmethod
    def _checksum(cls, value: str | None) -> str | None:
        return _validated_checksum(value)

    @field_validator("mime_types")
    @classmethod
    def _mime_lengths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(len(m) > 200 for m in value):
            raise ValueError("each mime type must be at most 200 characters")
        return value


class CreateUploadIntentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_id: str
    object_key: str
    upload_url: str
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class RegisterExternalAssetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_key: str
    bucket: str | None = Field(default=None, max_length=200)
    object_key: str = Field(max_length=500)
    mime_type: str = Field(max_length=200)
    byte_size: int = Field(ge=0)
    checksum_sha256: str | None = None
    alt_text: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("checksum_sha256")
    @classmethod
    def _checksum(cls, value: str | None) -> str | None:
        return _validated_checksum(value)


class UpdateAssetMetadataInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alt_text: str | None = None
    metadata: dict[str, Any] | None = None


class ResolvedAssetUrlDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    url: str
    expires_in_seconds: int


class FinalizeResultDTO(BaseModel):
    """Ack returned by FinalizeAsset; the asset becomes observable after
    the finalize workflow executes."""

    model_config = ConfigDict(extra="forbid")

    intent_id: str
    object_key: str
    state: str = "pending"
