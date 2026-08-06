"""Interaction facts owned by the interaction module."""

import uuid
from enum import StrEnum
from uuid import UUID

from sqlalchemy import ForeignKey, Index, SmallInteger, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, TimestampMixin, new_uuid7


class InteractionKind(StrEnum):
    LIKE = "like"
    RATING = "rating"


class Interaction(Base, TimestampMixin):
    __tablename__ = "interactions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "target_type",
            "target_id",
            "kind",
            name="uq_interactions_user_target_kind",
        ),
        Index("ix_interactions_user_kind_created", "user_id", "kind", "created_at"),
        Index("ix_interactions_target_kind", "target_type", "target_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    numeric_value: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
