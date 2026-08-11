"""Notification DTOs and command inputs.

Contract source: context/spec/capabilities/notification.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NotificationIntentDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    spec_key: str
    recipient_type: str
    recipient_id: str
    state: str
    requested_at: datetime
    cancelled_at: datetime | None = None


class NotificationDeliveryDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    intent_id: str
    channel: str
    provider_key: str
    masked_address: str
    attempt: int
    status: str
    provider_ref: str | None = None
    error_category: str | None = None
    next_retry_at: datetime | None = None
    delivered_at: datetime | None = None


class NotificationDeliveryRecordDTO(NotificationDeliveryDTO):
    spec_key: str
    recipient_type: str
    recipient_id: str
    requested_at: datetime
    created_at: datetime
    error_summary: str | None = None


class NotificationDeliveryAttemptDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    delivery_id: str
    delivery_attempt: int
    provider_sequence: int
    provider_key: str
    status: str
    provider_ref: str | None = None
    error_category: str | None = None
    error_summary: str | None = None
    started_at: datetime
    finished_at: datetime


class NotificationDeliveryPageDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NotificationDeliveryRecordDTO]
    total: int
    page: int
    size: int


class NotificationDeliveryDetailDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery: NotificationDeliveryRecordDTO
    attempts: list[NotificationDeliveryAttemptDTO]


class RequestNotificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_key: str
    recipient_type: str
    recipient_id: str
    variables: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=200)
    requested_at: datetime | None = None


class RequestNotificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: NotificationIntentDTO
    delivery: NotificationDeliveryDTO
    created: bool
