"""Access persistence models.

Contract source: context/spec/capabilities/access.md §3.

Subjects are opaque references: no foreign keys to identity or any other
capability. Scope values are stable strings: ``global`` or ``own``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin


@TableOwnership.owned_by("capability:access")
class AccessRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "access_roles"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


@TableOwnership.owned_by("capability:access")
class AccessRoleCapability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "access_role_capabilities"

    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("access_roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability_key: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        UniqueConstraint("role_id", "capability_key", name="uq_access_role_capability"),
    )


@TableOwnership.owned_by("capability:access")
class AccessSubjectRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "access_subject_roles"

    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("access_roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="global")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", "role_id", name="uq_access_subject_role"),
        Index("ix_access_subject_roles_subject", "subject_type", "subject_id"),
    )
