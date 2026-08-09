"""Points events.

Contract source: context/spec/capabilities/points.md §7.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    program_key: str
    subject_type: str
    subject_id: str


class AccountOpenedPayload(_Base):
    pass


class CreditedPayload(_Base):
    entry_id: str
    amount: int
    balance: int
    behavior_key: str | None = None
    source_type: str | None = None
    source_id: str | None = None


class DebitedPayload(_Base):
    entry_id: str
    amount: int
    balance: int
    behavior_key: str | None = None
    source_type: str | None = None
    source_id: str | None = None


class EntryReversedPayload(_Base):
    entry_id: str
    reversal_id: str
    amount: int
    balance: int


class BucketExpiredPayload(_Base):
    entry_id: str
    bucket_id: str
    expiration_identity: str
    amount: int
    balance: int


class AccountFrozenPayload(_Base):
    state: str


POINTS_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "points.account_opened.v1": AccountOpenedPayload,
    "points.credited.v1": CreditedPayload,
    "points.debited.v1": DebitedPayload,
    "points.entry_reversed.v1": EntryReversedPayload,
    "points.bucket_expired.v1": BucketExpiredPayload,
    "points.account_frozen.v1": AccountFrozenPayload,
}

for _key in POINTS_EVENT_SCHEMAS:
    validate_error_code(_key)
