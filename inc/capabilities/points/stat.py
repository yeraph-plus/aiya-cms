"""Points capability statistics provider."""

from __future__ import annotations

from typing import Any

from inc.capabilities.points.models import PointsLedgerEntry
from inc.kernel.observability.statistics import count_created


async def stat(*, uow_factory: Any, now: Any, window_days: int = 7) -> dict[str, Any]:
    return await count_created(
        uow_factory=uow_factory, model=PointsLedgerEntry, now=now, window_days=window_days
    )


class Provider:
    key = "points"

    def __init__(self, *, uow_factory: Any, clock: Any) -> None:
        self._uow_factory, self._clock = uow_factory, clock

    async def summary(self, *, window: str = "7d") -> dict[str, Any]:
        return await stat(
            uow_factory=self._uow_factory,
            now=self._clock.utc_now(),
            window_days={"24h": 1, "7d": 7, "30d": 30}[window],
        )
