"""Community capability statistics provider."""

from __future__ import annotations

from typing import Any

from inc.capabilities.community.models import CommunityDiscussion, CommunityPost
from inc.kernel.observability.statistics import count_created


class Provider:
    key = "community"

    def __init__(self, *, uow_factory: Any, clock: Any) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def summary(self, *, window: str = "7d") -> dict[str, Any]:
        days = {"24h": 1, "7d": 7, "30d": 30}[window]
        discussions = await count_created(
            uow_factory=self._uow_factory,
            model=CommunityDiscussion,
            now=self._clock.utc_now(),
            window_days=days,
        )
        posts = await count_created(
            uow_factory=self._uow_factory,
            model=CommunityPost,
            now=self._clock.utc_now(),
            window_days=days,
        )
        return {"discussions": discussions, "posts": posts}
