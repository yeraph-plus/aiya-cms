"""Membership DTOs and command inputs.

Contract source: context/spec/capabilities/membership.md §5/§6.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LevelDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level_key: str
    display_name: str
    tier_rank: int
    status: str
    cycle_days: int
    grant_points: int
    renewal_allowed: bool
    version: int = 1


class CreateLevelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level_key: str = Field(
        min_length=1, max_length=100, pattern=r"^[a-z0-9](?:[a-z0-9_]*[a-z0-9])?$"
    )
    display_name: str = Field(min_length=1, max_length=200)
    tier_rank: int = Field(gt=0)
    cycle_days: int = Field(gt=0)
    grant_points: int = Field(gt=0)
    renewal_allowed: bool = True


class UpdateLevelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    tier_rank: int | None = Field(default=None, gt=0)
    cycle_days: int | None = Field(default=None, gt=0)
    grant_points: int | None = Field(default=None, gt=0)
    renewal_allowed: bool | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> UpdateLevelInput:
        mutable_fields = {
            "display_name",
            "tier_rank",
            "cycle_days",
            "grant_points",
            "renewal_allowed",
        }
        if any(
            name in self.model_fields_set and getattr(self, name) is None for name in mutable_fields
        ):
            raise ValueError("patch fields must be omitted rather than null")
        return self


class LevelStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class MembershipSummaryDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level_count: int
    active_level_count: int
    subscription_count: int
    active_subscription_count: int
    cancelled_subscription_count: int
    expired_subscription_count: int


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
