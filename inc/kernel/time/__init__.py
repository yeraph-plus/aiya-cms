"""Clock and time handling primitives.

Contract source: context/spec/kernel/foundation.md §3.

All persisted times are UTC tz-aware datetimes. Testable logic obtains the
current time through a Clock; business days, user timezones and expiry
windows are explicit caller inputs, never the host local timezone.
"""

from __future__ import annotations

import time as _time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Source of the current UTC time."""

    def utc_now(self) -> datetime:
        """Current UTC tz-aware datetime (nanosecond or coarser precision)."""

        ...


class SystemClock:
    """Wall clock backed by the system clock."""

    def utc_now(self) -> datetime:
        return datetime.fromtimestamp(_time.time(), tz=UTC)


SYSTEM_CLOCK: Clock = SystemClock()
