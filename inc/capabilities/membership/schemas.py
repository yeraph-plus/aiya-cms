"""Membership DTOs and command inputs.

Contract source: context/spec/capabilities/membership.md §5/§6.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


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
    cycle_id: str | None = None
    cycle_points_amount: int | None = None
    source_type: str | None = None
    source_ref: str | None = None
    terminated_at: datetime | None = None
    version: int = 1


class MembershipCycleDTO(BaseModel):
    """Public snapshot of a membership cycle fact."""

    model_config = ConfigDict(extra="forbid")

    cycle_id: str
    subscription_id: str
    subject_type: str
    subject_id: str
    level_key: str
    cycle_start: datetime
    cycle_end: datetime
    cycle_points_amount: int
    state: str
    source_type: str
    source_ref: str
    points_entry_ref: str | None = None
    idempotency_key: str
    failure_code: str | None = None
    version: int = 1

    @property
    def id(self) -> str:
        """Keep the common resource accessor available without changing the contract."""

        return self.cycle_id


# ``fact`` is the domain term used by workflows; both names describe the
# same immutable public snapshot.
MembershipCycleFactDTO = MembershipCycleDTO


class CancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: str
    reason: str = Field(min_length=1, max_length=500)


class TerminateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: str
    reason: str = Field(min_length=1, max_length=500)


class PrepareSubscriptionCycleInput(BaseModel):
    """Input for the membership half of the prepare/attach protocol."""

    model_config = ConfigDict(extra="forbid")

    subject_type: str = Field(min_length=1, max_length=32)
    subject_id: str = Field(min_length=1, max_length=200)
    level_key: str = Field(min_length=1, max_length=100)
    source_type: str = Field(min_length=1, max_length=64)
    source_ref: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)
    expected_version: int | None = Field(default=None, ge=1)
    auto_renew: bool = False


class AttachPointsGrantInput(BaseModel):
    """Opaque points entry returned by the user-center workflow."""

    model_config = ConfigDict(extra="forbid")

    cycle_id: str = Field(min_length=1)
    points_entry_ref: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)


class MarkCycleFailedInput(BaseModel):
    """Permanent failure fact for a cycle that was not activated."""

    model_config = ConfigDict(extra="forbid")

    cycle_id: str = Field(min_length=1)
    failure_code: str = Field(
        min_length=1,
        max_length=200,
        validation_alias=AliasChoices("failure_code", "reason_code"),
    )
    idempotency_key: str = Field(min_length=1, max_length=200)
