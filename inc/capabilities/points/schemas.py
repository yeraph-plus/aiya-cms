"""Points DTOs and command inputs.

Contract source: context/spec/capabilities/points.md §5/§6.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BalanceDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    program_key: str
    subject_type: str
    subject_id: str
    state: str
    balance: int
    version: int


class BucketDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    account_id: str
    bucket_type: str
    expiration_identity: str | None = None
    expires_at: datetime | None = None
    amount: int
    version: int


class DebitAllocationDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_id: str
    amount: int


class LedgerEntryDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    account_id: str
    program_key: str
    amount: int
    entry_type: str
    behavior_key: str | None = None
    behavior_version: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    reversal_of: str | None = None
    allocations: list[DebitAllocationDTO] = Field(default_factory=list)
    created_at: datetime


class BehaviorCatalogDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    version: str
    program_key: str
    direction: str
    fixed_amount: int | None = None
    min_amount: int
    max_amount: int
    cooldown_seconds: int | None = None
    daily_limit: int | None = None
    business_timezone: str
    expiration_days: int | None = None


class CreditDebitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str
    subject_id: str
    amount: int = Field(gt=0)
    source_type: str
    source_id: str
    idempotency_key: str = Field(min_length=1, max_length=200)
    actor_type: str = "user"
    actor_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None  # explicit expiry; overrides behavior expiration_days


class AdjustInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str
    subject_id: str
    program_key: str = Field(min_length=1, max_length=100)
    amount: int  # nonzero; negative is a debit-style adjustment
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReverseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)
