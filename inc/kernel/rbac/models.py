"""RBAC persistence models and association tables."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, ForeignKey, String, Table, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inc.kernel.db import Base, TimestampMixin, new_uuid7

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        Uuid,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("organization_id", Uuid, nullable=True),
)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions,
        back_populates="roles",
        lazy="selectin",
    )


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("alias", name="permissions_alias_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions,
        back_populates="permissions",
        lazy="selectin",
    )
