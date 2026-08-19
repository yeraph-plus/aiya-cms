"""Membership event schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class _CycleSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subscription_id: str
    cycle_id: str
    subject_type: str
    subject_id: str
    level_key: str
    cycle_start: datetime
    cycle_end: datetime
    cycle_points_amount: int
    source_type: str
    source_ref: str


class CyclePreparedPayload(_CycleSnapshot):
    pass


class ActivatedPayload(_CycleSnapshot):
    points_entry_ref: str


class RenewedPayload(ActivatedPayload):
    pass


class CycleFailedPayload(_CycleSnapshot):
    failure_code: str


class _SubscriptionSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subscription_id: str
    subject_type: str
    subject_id: str
    level_key: str
    cycle_end: datetime


class CancelledPayload(_SubscriptionSnapshot):
    pass


class TerminatedPayload(_SubscriptionSnapshot):
    pass


class ExpiredPayload(_SubscriptionSnapshot):
    pass


MEMBERSHIP_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "membership.cycle_prepared.v1": CyclePreparedPayload,
    "membership.activated.v1": ActivatedPayload,
    "membership.renewed.v1": RenewedPayload,
    "membership.cancelled.v1": CancelledPayload,
    "membership.terminated.v1": TerminatedPayload,
    "membership.expired.v1": ExpiredPayload,
    "membership.cycle_failed.v1": CycleFailedPayload,
}

for _key in MEMBERSHIP_EVENT_SCHEMAS:
    validate_error_code(_key)
