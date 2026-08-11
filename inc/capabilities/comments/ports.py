"""Ports consumed by the comments capability."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

TargetExistsPort = Callable[[str, str], Awaitable[bool]]
"""Async ``(target_type, target_id) -> exists`` supplied by composition."""
