"""Taxonomy ports.

Contract source: context/spec/capabilities/taxonomy.md §1/§6.

The consumer-facing TargetExists Port lets the composition root validate
that assignment targets exist without taxonomy importing any capability.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

TargetExistsPort = Callable[[str, str], Awaitable[bool]]
"""Async ``(target_type, target_id) -> exists`` provided by the composition root."""

BatchTargetExistsPort = Callable[[str, list[str]], Awaitable[dict[str, bool]]]
"""Async bulk existence check used by diagnostics (report-only orphan scan)."""


class NullTargetExists:
    """Test/empty adapter: nothing exists (exercises the report path)."""

    async def __call__(self, target_type: str, target_id: str) -> bool:
        return False


class NullBatchTargetExists:
    async def __call__(self, target_type: str, target_ids: list[str]) -> dict[str, bool]:
        return {target_id: False for target_id in target_ids}
