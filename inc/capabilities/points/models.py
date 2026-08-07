"""Points persistence models.

Contract source: context/spec/capabilities/points.md §2/§3.

The ledger is the source of truth; balance is a same-transaction snapshot.
Subject/source/actor are opaque references with no cross-capability FKs.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin

ACCOUNT_STATES = ("active", "frozen", "debt")
ENTRY_TYPES = ("credit", "debit", "adjustment", "reversal")


class LedgerMetadata(BaseModel):
    """Schema-bound metadata envelope for ledger entries."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = {}


class BehaviorDefinitionData(BaseModel):
    """Non-executing mirror of a deployed behavior declaration."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = {}


@TableOwnership.owned_by("capability:points")
class PointsProgram(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "points_programs"

    program_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="points")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    allow_admin_reversal: Mapped[bool] = mapped_column(nullable=False, default=True)


@TableOwnership.owned_by("capability:points")
class PointsAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "points_accounts"

    program_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("points_programs.id"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "program_id", "subject_type", "subject_id", name="uq_points_accounts_program_subject"
        ),
    )


@TableOwnership.owned_by("capability:points")
class PointsBalance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "points_balances"

    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("points_accounts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


@TableOwnership.owned_by("capability:points")
class PointsLedgerEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "points_ledger_entries"

    program_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("points_programs.id"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("points_accounts.id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)
    behavior_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    behavior_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    entry_metadata: Mapped[LedgerMetadata] = mapped_column(
        JsonBModel(LedgerMetadata, "1"), nullable=False
    )
    reversal_of: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("points_ledger_entries.id"), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "program_id", "idempotency_key", name="uq_points_ledger_program_idempotency"
        ),
    )


@TableOwnership.owned_by("capability:points")
class PointsBehaviorDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "points_behavior_definitions"

    behavior_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    program_key: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    data: Mapped[BehaviorDefinitionData] = mapped_column(
        JsonBModel(BehaviorDefinitionData, "1"), nullable=False
    )
