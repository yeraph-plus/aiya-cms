"""Assets DTOs and command inputs.

Contract source: context/spec/capabilities/assets.md §2/§5.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class CreateUploadIntentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_key: str
    mime_types: tuple[str, ...] = Field(min_length=1)
    content_length_max: int = Field(gt=0, le=100 * 1024 * 1024)
    checksum_sha256: str | None = None


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
    bucket: str | None = None
    object_key: str
    mime_type: str
    byte_size: int = Field(ge=0)
    checksum_sha256: str | None = None
    alt_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
