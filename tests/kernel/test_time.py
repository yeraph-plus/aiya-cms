"""Clock contract tests (foundation.md §3/§7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from inc.kernel.time import Clock, SystemClock
from inc.kernel.time.fake import FakeClock


def test_system_clock_returns_tz_aware_utc() -> None:
    now = SystemClock().utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert abs((datetime.now(UTC) - now).total_seconds()) < 5


def test_system_clock_conforms_to_protocol() -> None:
    clock: Clock = SystemClock()
    assert isinstance(clock.utc_now(), datetime)


def test_fake_clock_advances_and_jumps() -> None:
    clock = FakeClock()
    start = clock.utc_now()
    clock.advance(timedelta(seconds=90))
    assert clock.utc_now() - start == timedelta(seconds=90)
    target = datetime(2030, 6, 1, tzinfo=UTC)
    clock.set(target)
    assert clock.utc_now() == target


def test_fake_clock_rejects_naive_datetime() -> None:
    clock = FakeClock()
    with pytest.raises(ValueError):
        clock.set(datetime(2026, 1, 1))


def test_fake_clock_drives_expiry_math() -> None:
    clock = FakeClock()
    deadline = clock.utc_now() + timedelta(minutes=5)
    assert not clock.utc_now() >= deadline
    clock.advance(timedelta(minutes=6))
    assert clock.utc_now() >= deadline
