"""Deterministic test clock.

Contract source: context/spec/kernel/foundation.md §7.

FakeClock is a kernel test adapter: it makes expiry, retry and business-day
logic testable without sleeping or monkeypatching the system clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class FakeClock:
    """Clock whose current time is advanced explicitly."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def utc_now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        """Advance the clock by *delta*."""

        self._now += delta

    def set(self, value: datetime) -> None:
        """Jump the clock to an explicit instant (must stay tz-aware)."""

        if value.tzinfo is None:
            raise ValueError("FakeClock requires tz-aware datetimes")
        self._now = value
