"""Identity domain models: user profile, login identities, org placeholder.

Contract source: context/spec/kernel.md.
"""

import uuid
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, Uuid, false
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, TimestampMixin, new_uuid7


class UserStatus(StrEnum):
    ACTIVE = "active"
    BANNED = "banned"
    DELETED = "deleted"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        default=UserStatus.ACTIVE.value,
        server_default=UserStatus.ACTIVE.value,
        nullable=False,
    )


class Identity(Base, TimestampMixin):
    __tablename__ = "identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_uid", name="identities_provider_uid_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_uid: Mapped[str] = mapped_column(String(320), nullable=False)
    secret_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
