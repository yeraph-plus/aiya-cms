"""ORM base, UUIDv7 and timestamp conventions.

Contract source: context/spec/kernel/database.md §1.

``Base`` provides the shared metadata; it owns no business tables. Table
ownership is declared per model via the TableOwnership decorator, not by
package location.
"""

from __future__ import annotations

import secrets
import sys
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from inc.kernel.time import SYSTEM_CLOCK


class Base(DeclarativeBase):
    """Shared declarative base for kernel and capability models."""


_uuid7_lock = threading.Lock()
_last_uuid7_ms = 0
_uuid7_counter = 0


def new_uuid7() -> uuid.UUID:
    """App-side UUIDv7 primary key default.

    Python 3.14 provides ``uuid.uuid7``.  The fallback keeps local 3.12/3.13
    verification deterministic and preserves the UUIDv7 ordering contract
    instead of delegating ordering to random UUID4 values.
    """

    if sys.version_info >= (3, 14) and hasattr(uuid, "uuid7"):
        return uuid.uuid7()
    global _last_uuid7_ms, _uuid7_counter
    now_ms = time.time_ns() // 1_000_000
    with _uuid7_lock:
        if now_ms <= _last_uuid7_ms:
            _uuid7_counter = (_uuid7_counter + 1) & 0xFFF
        else:
            _last_uuid7_ms = now_ms
            _uuid7_counter = 0
        value = (
            ((now_ms & ((1 << 48) - 1)) << 80)
            | (0x7 << 76)
            | (_uuid7_counter << 64)
            | (0x2 << 62)
            | secrets.randbits(62)
        )
    return uuid.UUID(int=value)


def _utc_now() -> datetime:
    return SYSTEM_CLOCK.utc_now()


class TimestampMixin:
    """App-side tz-aware created_at/updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )


class UUIDPrimaryKeyMixin:
    """Conventional UUIDv7 primary key named ``id``."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid7)

    def __eq__(self, other: Any) -> bool:
        # Unsaved instances have id is None until flush; only compare equal by
        # identity so two distinct transient rows never collide. Compare against
        # the mixin type, not type(self), so equality stays symmetric across
        # subclasses, and return NotImplemented for foreign types so Python can
        # try the reflected comparison.
        if not isinstance(other, Base):
            return NotImplemented
        self_id = getattr(self, "id", None)
        other_id = getattr(other, "id", None)
        if self_id is None or other_id is None:
            return self is other
        return bool(self_id == other_id)

    def __hash__(self) -> int:
        # id changes from None to a UUID after flush; keep the hash stable for
        # that transition so sets/dicts keyed before persist keep working.
        value = getattr(self, "id", None)
        return hash(value) if value is not None else id(self)
