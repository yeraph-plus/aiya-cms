"""Archive delivery Port and provider-neutral typed results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import parse_qsl, urlsplit

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from inc.capabilities.archive.models import ArchiveExternalLocator
from inc.kernel.errors import ErrorCategory, KernelError

__all__ = [
    "ArchiveAvailability",
    "ArchiveDelivery",
    "ArchiveDeliveryProvider",
    "ArchiveDeliveryRequest",
    "ArchiveDeliveryResult",
    "ArchiveExternalLocator",
    "ArchiveFileFact",
    "ArchiveProviderError",
    "ArchiveSettingsSnapshot",
    "Availability",
    "DeliveryRequest",
    "ExternalLocator",
    "FakeArchiveDeliveryProvider",
    "FakeArchiveProvider",
    "ProviderAvailability",
    "ProviderChild",
    "ProviderDelivery",
    "ProviderFileFact",
    "ProviderOperationResult",
]


class ArchiveSettingsSnapshot(BaseModel):
    """Opaque per-call settings snapshot owned by the composition root."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(default_factory=dict)

    def __repr__(self) -> str:
        return f"ArchiveSettingsSnapshot(keys={tuple(sorted(self.values))!r})"

    def __str__(self) -> str:
        return repr(self)


class ArchiveAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    available: bool
    reason_code: str | None = Field(
        default=None, validation_alias=AliasChoices("reason_code", "reason")
    )
    contract_version: str | None = None
    retry_after_seconds: int | None = Field(default=None, ge=0)

    @property
    def reason(self) -> str | None:
        return self.reason_code


class ProviderFileFact(BaseModel):
    """Provider file metadata with an explicit unavailable outcome."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "unavailable"] = "available"
    display_name: str | None = Field(
        default=None,
        max_length=500,
        validation_alias=AliasChoices("display_name", "name"),
    )
    size_bytes: int | None = Field(default=None, gt=0)
    checksum_algorithm: str | None = Field(default=None, max_length=32)
    checksum_value: str | None = Field(default=None, max_length=256)
    provider_fact_version: str | None = Field(
        default=None,
        max_length=64,
        validation_alias=AliasChoices("provider_fact_version", "fact_version"),
    )
    reason_code: str | None = Field(default=None, max_length=64)
    retry_after_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _fact_shape(self) -> ProviderFileFact:
        if self.status == "available" and (self.size_bytes is None or not self.display_name):
            raise ValueError("available provider fact requires name and positive size")
        return self

    @property
    def available(self) -> bool:
        return self.status == "available"


class ArchiveDeliveryRequest(BaseModel):
    """Provider-neutral request; the provider owns interpretation of locator."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    locator: ArchiveExternalLocator = Field(
        validation_alias=AliasChoices("locator", "external_locator")
    )
    item_ref: str = Field(min_length=1, max_length=200)
    expires_at: datetime
    provider_contract_version: str = Field(default="1", min_length=1, max_length=32)

    @model_validator(mode="after")
    def _expiry_is_utc(self) -> ArchiveDeliveryRequest:
        if self.expires_at.tzinfo is None:
            object.__setattr__(self, "expires_at", self.expires_at.replace(tzinfo=UTC))
        return self


class ProviderDelivery(BaseModel):
    """Browser-safe delivery result.

    A provider URL that needs any provider header is represented as
    ``proxy_required``. Headers are intentionally not modeled at all.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["redirect", "proxy", "proxy_required", "unavailable", "failed", "unknown"] = (
        Field(default="unavailable", validation_alias=AliasChoices("status", "kind"))
    )
    provider_delivery_ref: str | None = Field(default=None, max_length=500)
    redirect_url: str | None = None
    proxy_ticket: str | None = Field(default=None, max_length=500)
    expires_at: datetime | None = None
    reason_code: str | None = Field(default=None, max_length=64)
    retry_after_seconds: int | None = Field(default=None, ge=0)

    @field_validator("provider_delivery_ref", "proxy_ticket")
    @classmethod
    def _opaque_value(cls, value: str | None) -> str | None:
        if value is not None and ("://" in value or "\r" in value or "\n" in value):
            raise ValueError("provider delivery values must be opaque")
        return value

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

    @model_validator(mode="after")
    def _delivery_shape(self) -> ProviderDelivery:
        if self.status == "redirect" and not self.redirect_url:
            raise ValueError("redirect delivery requires redirect_url")
        if self.status == "proxy" and not self.proxy_ticket:
            raise ValueError("proxy delivery requires proxy_ticket")
        if self.status in {"proxy_required", "unavailable", "failed", "unknown"}:
            if self.redirect_url is not None or self.proxy_ticket is not None:
                raise ValueError("non-browser delivery cannot carry a delivery target")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            object.__setattr__(self, "expires_at", self.expires_at.replace(tzinfo=UTC))
        return self

    @property
    def proxy_required(self) -> bool:
        return self.status == "proxy_required"

    @property
    def kind(self) -> str:
        return self.status

    @property
    def browser_safe(self) -> bool:
        return self.status in {"redirect", "proxy"}


class ProviderOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "unsupported", "unavailable", "failed"]
    reason_code: str | None = Field(default=None, max_length=64)


class ProviderChild(BaseModel):
    """Explicit admin import result; never used by user delivery GETs."""

    model_config = ConfigDict(extra="forbid")

    locator: ArchiveExternalLocator
    display_name: str = Field(min_length=1, max_length=500)
    size_bytes: int | None = Field(default=None, gt=0)
    is_directory: bool = False


class ArchiveProviderError(KernelError):
    """Provider failure with a safe, stable reason and no raw response body."""

    def __init__(
        self,
        *,
        reason_code: str = "archive.provider_unavailable",
        category: ErrorCategory = ErrorCategory.DEPENDENCY_UNAVAILABLE,
        message: str = "archive provider unavailable",
    ) -> None:
        del message
        super().__init__(
            code=reason_code, category=category, message="archive provider unavailable"
        )
        self.reason_code = reason_code


class ArchiveDeliveryProvider(Protocol):
    """External download provider boundary owned by archive."""

    key: str

    async def check_availability(
        self, settings_snapshot: ArchiveSettingsSnapshot | None = None
    ) -> ArchiveAvailability: ...

    async def stat(
        self,
        external_locator: ArchiveExternalLocator,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderFileFact: ...

    async def create_delivery(
        self,
        request: ArchiveDeliveryRequest,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderDelivery: ...

    async def refresh_delivery(
        self,
        provider_delivery_ref: str,
        request: ArchiveDeliveryRequest,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderDelivery: ...

    async def revoke_delivery(
        self,
        provider_delivery_ref: str,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderOperationResult: ...

    async def list_children(
        self,
        external_locator: ArchiveExternalLocator,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> tuple[ProviderChild, ...]: ...


class FakeArchiveDeliveryProvider:
    """Provider-neutral in-memory Port implementation for capability tests."""

    key = "archive.fake"
    contract_version = "fake.v1"

    def __init__(self) -> None:
        self.facts: dict[str, ProviderFileFact] = {}
        self.deliveries: dict[str, ProviderDelivery] = {}
        self.calls: list[str] = []
        self.available = True
        self.availability_reason: str | None = None
        self._counter = 0

    def add_file(
        self,
        locator: str | ArchiveExternalLocator,
        *,
        display_name: str,
        size_bytes: int,
        checksum_algorithm: str | None = None,
        checksum_value: str | None = None,
        delivery: ProviderDelivery | None = None,
    ) -> None:
        key = locator if isinstance(locator, str) else locator.value
        self.facts[key] = ProviderFileFact(
            display_name=display_name,
            size_bytes=size_bytes,
            checksum_algorithm=checksum_algorithm,
            checksum_value=checksum_value,
            provider_fact_version=self.contract_version,
        )
        if delivery is not None:
            self.deliveries[key] = delivery

    async def check_availability(
        self, settings_snapshot: ArchiveSettingsSnapshot | None = None
    ) -> ArchiveAvailability:
        del settings_snapshot
        return ArchiveAvailability(
            available=self.available,
            reason_code=None if self.available else self.availability_reason,
            contract_version=self.contract_version,
        )

    async def stat(
        self,
        external_locator: ArchiveExternalLocator,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderFileFact:
        del settings_snapshot
        self.calls.append(f"stat:{external_locator.value}")
        if not self.available:
            return ProviderFileFact(
                status="unavailable", reason_code=self.availability_reason or "provider_unavailable"
            )
        return self.facts.get(
            external_locator.value,
            ProviderFileFact(status="unavailable", reason_code="not_found"),
        )

    async def create_delivery(
        self,
        request: ArchiveDeliveryRequest,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderDelivery:
        del settings_snapshot
        self.calls.append(f"create:{request.item_ref}")
        configured = self.deliveries.get(request.locator.value)
        if configured is not None:
            return configured
        self._counter += 1
        return ProviderDelivery(
            status="proxy",
            provider_delivery_ref=f"fake-delivery-{self._counter}",
            proxy_ticket=f"fake-ticket-{self._counter}",
            expires_at=request.expires_at,
        )

    async def refresh_delivery(
        self,
        provider_delivery_ref: str,
        request: ArchiveDeliveryRequest,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderDelivery:
        del settings_snapshot
        self.calls.append(f"refresh:{provider_delivery_ref}")
        return ProviderDelivery(
            status="proxy",
            provider_delivery_ref=provider_delivery_ref,
            proxy_ticket=f"refreshed-{provider_delivery_ref}",
            expires_at=request.expires_at,
        )

    async def revoke_delivery(
        self,
        provider_delivery_ref: str,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderOperationResult:
        del settings_snapshot
        self.calls.append(f"revoke:{provider_delivery_ref}")
        return ProviderOperationResult(status="completed")

    async def list_children(
        self,
        external_locator: ArchiveExternalLocator,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> tuple[ProviderChild, ...]:
        del settings_snapshot
        fact = self.facts.get(external_locator.value)
        if fact is None or not fact.available:
            return ()
        return (
            ProviderChild(
                locator=external_locator,
                display_name=fact.display_name or external_locator.value,
                size_bytes=fact.size_bytes,
            ),
        )


# Short names used in provider contracts and tests.
Availability = ArchiveAvailability
DeliveryRequest = ArchiveDeliveryRequest
ArchiveFileFact = ProviderFileFact
FakeArchiveProvider = FakeArchiveDeliveryProvider
ProviderAvailability = ArchiveAvailability
ArchiveDelivery = ProviderDelivery
ArchiveDeliveryResult = ProviderDelivery
ExternalLocator = ArchiveExternalLocator
