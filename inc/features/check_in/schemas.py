"""Check-in and points self-service HTTP DTOs.

Contract source: context/spec/features.md §4.3, http-openapi.md §3.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CheckInResultDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str  # "rewarded" | "already_rewarded"
    business_date: str
    balance: int


class BalanceViewDTO(BaseModel):
    """Self-service balance; unopened accounts get an explicit empty view."""

    model_config = ConfigDict(extra="forbid")

    opened: bool
    program_key: str
    balance: int = 0
