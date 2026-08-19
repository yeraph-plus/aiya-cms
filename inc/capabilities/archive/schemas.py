"""Archive capability boundary DTOs.

Public item, grant and delivery DTOs intentionally contain only opaque
references and public facts. Provider locators, credentials, raw URLs and
headers are not fields on the public persistence DTOs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from inc.capabilities.archive.models import ArchiveExternalLocator


def _non_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must not be blank")
    return value


class ArchiveLocatorInput(BaseModel):
    """Trusted registration input for a provider reference.

    This type is accepted only by named archive Commands. It cannot represent
    URLs, credentials or request headers.
    """

    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=4096)
    schema_version: str = Field(default="1", min_length=1, max_length=32)

    @field_validator("value")
    @classmethod
    def _validate(cls, value: str) -> str:
        return ArchiveExternalLocator(value=value).value


class RegisterArchiveItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: str = Field(min_length=1, max_length=200)
    provider_key: str = Field(min_length=1, max_length=64)
    provider_contract_version: str = Field(default="1", min_length=1, max_length=32)
    external_locator: ArchiveLocatorInput = Field(
        validation_alias=AliasChoices("external_locator", "locator")
    )
    display_name: str = Field(min_length=1, max_length=500)
    size_bytes: int = Field(gt=0, le=4 * 1024 * 1024 * 1024)
    part_number: int = Field(gt=0)
    checksum_algorithm: str | None = Field(default=None, max_length=32)
    checksum_value: str | None = Field(default=None, max_length=256)

    @field_validator("item_key", "provider_key", "provider_contract_version", "display_name")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return _non_empty(value)


class VerifyArchiveItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    expected_version: int | None = Field(default=None, ge=1)


class ArchiveItemStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    expected_version: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=500)


class MigrateArchiveItemProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    provider_key: str = Field(min_length=1, max_length=64)
    provider_contract_version: str = Field(default="1", min_length=1, max_length=32)
    external_locator: ArchiveLocatorInput = Field(
        validation_alias=AliasChoices("external_locator", "locator")
    )
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(default="provider migration", min_length=1, max_length=500)


class IssueDownloadGrantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str = Field(min_length=1, max_length=64)
    subject_id: str = Field(min_length=1, max_length=200)
    product_ref: str | None = Field(
        default=None,
        max_length=200,
        validation_alias=AliasChoices("product_ref", "product_id"),
    )
    quote_ref: str | None = Field(
        default=None,
        max_length=200,
        validation_alias=AliasChoices("quote_ref", "quote_id"),
    )
    points_entry_ref: str | None = Field(
        default=None,
        max_length=200,
        validation_alias=AliasChoices("points_entry_ref", "points_entry_id"),
    )
    target_type: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=200)
    item_ids: tuple[str, ...] = Field(
        min_length=1,
        validation_alias=AliasChoices("item_ids", "archive_item_ids", "item_refs"),
    )
    manifest_version: str = Field(min_length=1, max_length=64)
    manifest_digest: str | None = Field(default=None, min_length=1, max_length=128)
    valid_from: datetime | None = None
    expires_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=500)
    business_consumption_ref: str | None = Field(
        default=None,
        max_length=500,
        validation_alias=AliasChoices(
            "business_consumption_ref", "consumption_key", "business_consumption_key"
        ),
    )

    @field_validator("item_ids")
    @classmethod
    def _unique_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("item_ids must be unique")
        return value


class GrantStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: str
    expected_version: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=500)


class RecordDeliveryAttemptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: str
    item_id: str
    provider_key: str = Field(min_length=1, max_length=64)
    attempt_number: int = Field(gt=0)
    status: Literal[
        "pending",
        "delivered",
        "proxy_required",
        "failed",
        "expired",
        "revoked",
        "unknown",
    ]
    reason_code: str | None = Field(default=None, max_length=64)
    provider_delivery_ref: str | None = Field(default=None, max_length=500)
    link_expires_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("provider_delivery_ref")
    @classmethod
    def _opaque_ref(cls, value: str | None) -> str | None:
        if value is not None and ("://" in value or "\r" in value or "\n" in value):
            raise ValueError("provider_delivery_ref must be opaque")
        return value


class ArchiveItemDTO(BaseModel):
    """Public archive item DTO; provider identity and locator are omitted."""

    model_config = ConfigDict(extra="forbid")

    id: str
    item_key: str
    display_name: str
    size_bytes: int
    part_number: int
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    state: Literal["pending", "active", "unavailable", "retired"]
    version: int
    created_at: datetime
    updated_at: datetime


class ArchiveItemAdminDTO(ArchiveItemDTO):
    """Admin DTO with only a digest/kind summary of the protected locator."""

    provider_key: str
    provider_contract_version: str
    provider_fact_version: str | None = None
    last_verified_at: datetime | None = None
    unavailable_reason: str | None = None
    locator_digest: str
    locator_kind: str


class ArchiveItemPageDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ArchiveItemAdminDTO]
    total: int
    page: int
    size: int


class ArchiveGrantItemDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    item_key: str
    version: int
    part_number: int
    display_name: str
    size_bytes: int
    checksum_algorithm: str | None = None
    checksum_value: str | None = None


class DownloadGrantDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    subject_type: str
    subject_id: str
    product_ref: str | None = None
    quote_ref: str | None = None
    points_entry_ref: str | None = None
    target_type: str
    target_id: str
    manifest_version: str
    manifest_digest: str
    items: list[ArchiveGrantItemDTO]
    status: Literal["pending", "active", "expired", "revoked", "failed"]
    valid_from: datetime
    expires_at: datetime
    version: int
    created_at: datetime
    updated_at: datetime


class DownloadGrantAdminDTO(DownloadGrantDTO):
    """Admin grant view; it still contains no idempotency secret or locator."""

    idempotency_key_digest: str


class ArchiveGrantPageDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DownloadGrantAdminDTO]
    total: int
    page: int
    size: int


class DownloadGrantPageDTO(BaseModel):
    """Subject-facing grant page without administrator-only digests."""

    model_config = ConfigDict(extra="forbid")

    items: list[DownloadGrantDTO]
    total: int
    page: int
    size: int


class ArchiveItemPatchInput(BaseModel):
    """Admin-safe mutable item metadata accepted by the named update service."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=500)
    checksum_algorithm: str | None = Field(default=None, max_length=32)
    checksum_value: str | None = Field(default=None, max_length=256)
    expected_version: int | None = Field(default=None, ge=1)


class DeliveryAttemptDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    grant_id: str
    item_id: str
    provider_key: str
    attempt_number: int
    status: Literal[
        "pending",
        "delivered",
        "proxy_required",
        "failed",
        "expired",
        "revoked",
        "unknown",
    ]
    reason_code: str | None = None
    provider_delivery_ref: str | None = None
    link_expires_at: datetime | None = None
    started_at: datetime
    completed_at: datetime | None = None


class ArchiveDeliveryLinkDTO(BaseModel):
    """Short-lived browser-safe result returned by the delivery Activity."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    attempt_id: str | None = None
    status: Literal["redirect", "proxy", "proxy_required", "unavailable", "failed", "unknown"] = (
        Field(default="unavailable", validation_alias=AliasChoices("status", "kind"))
    )
    redirect_url: str | None = None
    proxy_ticket: str | None = None
    expires_at: datetime | None = None
    reason_code: str | None = None

    @field_validator("redirect_url")
    @classmethod
    def _safe_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("redirect_url must be an HTTPS browser-safe URL")
        secret_names = {
            "access_token",
            "api_key",
            "apikey",
            "authorization",
            "credential",
            "password",
            "secret",
            "token",
        }
        if any(key.lower() in secret_names for key, _ in parse_qsl(parsed.query)):
            raise ValueError("redirect_url contains a credential query parameter")
        return value

    @field_validator("proxy_ticket")
    @classmethod
    def _opaque_ticket(cls, value: str | None) -> str | None:
        if value is not None and ("://" in value or "\r" in value or "\n" in value):
            raise ValueError("proxy_ticket must be opaque")
        return value

    @property
    def kind(self) -> str:
        return self.status


class ResolveDownloadLinksDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: str
    links: list[ArchiveDeliveryLinkDTO]
    expires_at: datetime


class GrantCostBasisDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: str
    file_count: int
    size_bytes: int
    manifest_digest: str


# Stable aliases used by callers that name the aggregate explicitly.
ArchiveGrantDTO = DownloadGrantDTO
ArchiveDownloadGrantDTO = DownloadGrantDTO
ArchiveGrantPublicDTO = DownloadGrantDTO
ArchiveDeliveryAttemptDTO = DeliveryAttemptDTO
ArchiveDeliveryAttemptPublicDTO = DeliveryAttemptDTO
ArchiveItemPublicDTO = ArchiveItemDTO
ProviderLocatorInput = ArchiveLocatorInput
