"""Check-in and points self-service HTTP DTOs.

Contract source: context/spec/features.md §4.3, http-openapi.md §3.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class MeDTO(BaseModel):
    """Cross-capability self-service read model for the authenticated subject."""

    model_config = ConfigDict(extra="forbid")

    subject_id: str
    username: str | None = None
    display_name: str | None = None
    avatar_asset_id: str | None = None
    avatar_url: str | None = None
    status: str
    capabilities: list[str] = Field(default_factory=list)
    points: BalanceViewDTO | None = None
