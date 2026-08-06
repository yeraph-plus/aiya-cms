"""Kernel comment ORM models and JSONB boundary."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TimestampMixin, new_uuid7


class CommentStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SPAM = "spam"


class CommentExtra(BaseModel):
    model_config = ConfigDict(extra="allow")

    edited: bool = False
    deleted: bool = False
    flags: list[str] = Field(default_factory=list)


def _empty_extra() -> CommentExtra:
    return CommentExtra.model_validate({})


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_target", "target_type", "target_id", "status", "created_at", "id"),
        Index("ix_comments_root", "root_id"),
        Index("ix_comments_owner", "owner_id"),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("comments.id"), nullable=True)
    root_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CommentStatus.PENDING.value
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[CommentExtra] = mapped_column(
        JsonBModel(CommentExtra), nullable=False, default=_empty_extra
    )
