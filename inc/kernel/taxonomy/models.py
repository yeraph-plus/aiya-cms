"""Kernel taxonomy ORM models and JSONB boundary."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TimestampMixin, new_uuid7


class TermData(BaseModel):
    model_config = ConfigDict(extra="allow")

    description: str | None = None
    image_url: str | None = None

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> TermData:
        return super().model_validate(obj, **kwargs)


def _empty_data() -> TermData:
    return TermData.model_validate({})


class Term(Base, TimestampMixin):
    __tablename__ = "terms"
    __table_args__ = (
        UniqueConstraint("content_type", "group", "slug", name="uq_terms_type_group_slug"),
        Index("ix_terms_content_type", "content_type"),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    group: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    data: Mapped[TermData] = mapped_column(
        JsonBModel(TermData), nullable=False, default=_empty_data
    )


class TermRelationship(Base):
    __tablename__ = "term_relationships"
    __table_args__ = (
        Index("ix_term_rel_term", "term_id", "content_id"),
        {"extend_existing": True},
    )

    content_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    term_id: Mapped[UUID] = mapped_column(
        ForeignKey("terms.id", ondelete="CASCADE"), primary_key=True
    )
