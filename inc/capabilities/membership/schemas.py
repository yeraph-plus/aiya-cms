"""Membership DTOs and command inputs.

Contract source: context/spec/capabilities/membership.md §5/§6.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LevelDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level_key: str
    display_name: str
    tier_rank: int
    status: str
    cycle_days: int
    grant_points: int
    renewal_allowed: bool


class SubscriptionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    subject_type: str
    subject_id: str
    level_key: str
    cycle_start: datetime
    cycle_end: datetime
    status: str
    auto_renew: bool
    granted_points: int
    renewal_count: int
    cancelled_at: datetime | None = None
    expired_at: datetime | None = None


class RenewalRecordDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    subscription_id: str
    cycle_start: datetime
    cycle_end: datetime
    granted_points: int
    points_source_id: str
    outcome: str


class SubscribeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str
    subject_id: str
    level_key: str = Field(min_length=1, max_length=100)
    auto_renew: bool = False
    idempotency_key: str = Field(min_length=1, max_length=200)


class RenewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: str
    idempotency_key: str = Field(min_length=1, max_length=200)


class CancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: str
    reason: str = Field(min_length=1, max_length=500)


class TerminateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: str
    reason: str = Field(min_length=1, max_length=500)
