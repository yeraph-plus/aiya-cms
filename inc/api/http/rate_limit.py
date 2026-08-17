"""Small in-process fixed-window limiters for public HTTP endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class FixedWindowRateLimiter:
    limit: int
    window_seconds: int
    max_keys: int = 10_000
    _windows: dict[str, tuple[int, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("rate limiter limit must be positive")
        if self.window_seconds <= 0:
            raise ValueError("rate limiter window must be positive")
        if self.max_keys <= 0:
            raise ValueError("rate limiter max_keys must be positive")

    def allow(self, key: str, now: datetime) -> bool:
        window = int(now.timestamp()) // self.window_seconds
        self._prune(window)
        if key not in self._windows:
            # A hostile stream of unique keys must not turn this process-local
            # guard into an unbounded memory sink. Dict insertion order gives
            # us a deterministic oldest-entry eviction policy.
            while len(self._windows) >= self.max_keys:
                self._windows.pop(next(iter(self._windows)))
        current_window, count = self._windows.get(key, (window, 0))
        if current_window != window:
            count = 0
            current_window = window
        if count >= self.limit:
            self._windows[key] = (current_window, count)
            return False
        self._windows[key] = (current_window, count + 1)
        return True

    def _prune(self, current_window: int) -> None:
        expired = [
            key for key, (window, _count) in self._windows.items() if window != current_window
        ]
        for key in expired:
            self._windows.pop(key, None)
