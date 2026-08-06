"""Test-only models shared by kernel tests (not collected by pytest)."""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AppliedEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Test-only business side-effect table used by kernel handler tests."""

    __tablename__ = "test_applied_events"

    handler_key: Mapped[str] = mapped_column(String(200), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
