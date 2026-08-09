"""Membership events.

Contract source: context/spec/capabilities/membership.md §8.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: str
    subject_type: str
    subject_id: str


class SubscribedPayload(_Base):
    level_key: str
    cycle_start: datetime
    cycle_end: datetime
    granted_points: int


class RenewedPayload(_Base):
    level_key: str
    cycle_start: datetime
    cycle_end: datetime
    granted_points: int


class CancelledPayload(_Base):
    level_key: str
    cycle_end: datetime


class ExpiredPayload(_Base):
    level_key: str
    cycle_end: datetime


class TerminatedPayload(_Base):
    level_key: str
    cycle_end: datetime


MEMBERSHIP_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "membership.subscribed.v1": SubscribedPayload,
    "membership.renewed.v1": RenewedPayload,
    "membership.cancelled.v1": CancelledPayload,
    "membership.expired.v1": ExpiredPayload,
    "membership.terminated.v1": TerminatedPayload,
}

for _key in MEMBERSHIP_EVENT_SCHEMAS:
    validate_error_code(_key)
