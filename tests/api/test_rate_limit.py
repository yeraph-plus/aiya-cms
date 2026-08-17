from __future__ import annotations

from datetime import UTC, datetime, timedelta

from inc.api.http.rate_limit import FixedWindowRateLimiter
from inc.kernel.security.network import resolve_client_ip


def test_fixed_window_rate_limiter_prunes_expired_and_bounds_keys() -> None:
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60, max_keys=2)
    start = datetime(2026, 1, 1, tzinfo=UTC)

    assert limiter.allow("first", start)
    assert limiter.allow("second", start)
    # A new attacker-controlled key cannot grow the process forever.
    assert limiter.allow("third", start)
    assert len(limiter._windows) == 2

    # Expired windows are removed before the next decision.
    assert limiter.allow("fresh", start + timedelta(seconds=120))
    assert set(limiter._windows) == {"fresh"}


def test_forwarded_for_is_used_only_from_a_trusted_proxy() -> None:
    assert (
        resolve_client_ip(
            peer="198.51.100.10",
            forwarded_for="203.0.113.5",
            trusted_proxy_cidrs=(),
        )
        == "198.51.100.10"
    )
    assert (
        resolve_client_ip(
            peer="127.0.0.1",
            forwarded_for="198.51.100.10, 203.0.113.5",
            trusted_proxy_cidrs=("127.0.0.1/32",),
        )
        == "203.0.113.5"
    )
