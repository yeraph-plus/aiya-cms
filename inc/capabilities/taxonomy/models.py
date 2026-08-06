"""Taxonomy persistence models.

Contract source: context/spec/capabilities/taxonomy.md §3.

The dimension row is a non-executing mirror of the code declaration,
maintained by migration/ops for constraints and audit; assignments carry
opaque target ids with no foreign keys.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin


class TermData(BaseModel):
    """Schema-bound optional term metadata (validated via DimensionSpec)."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = {}


@TableOwnership.owned_by("capability:taxonomy")
class TaxonomyDimension(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "taxonomy_dimensions"

    dimension_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    spec_version: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


@TableOwnership.owned_by("capability:taxonomy")
class TaxonomyTerm(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "taxonomy_terms"

    dimension_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    term_metadata: Mapped[TermData] = mapped_column(JsonBModel(TermData, "1"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("dimension_key", "slug", name="uq_taxonomy_terms_dimension_slug"),
    )


@TableOwnership.owned_by("capability:taxonomy")
class TaxonomyAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "taxonomy_assignments"

    dimension_key: Mapped[str] = mapped_column(String(100), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("taxonomy_terms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    position: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "dimension_key",
            "target_type",
            "target_id",
            "term_id",
            name="uq_taxonomy_assignments_target_term",
        ),
        Index(
            "ix_taxonomy_assignments_term_target",
            "term_id",
            "target_type",
            "target_id",
        ),
    )
