"""Read-only table count primitive for capability-owned stat providers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from inc.kernel.db import UoWFactory


async def count_created(
    *,
    uow_factory: UoWFactory,
    model: Any,
    now: datetime,
    window_days: int,
) -> dict[str, int]:
    """Return total rows and rows created in the selected fixed window."""

    since = now - timedelta(days=window_days)
    async with uow_factory() as uow:
        total = await uow.session.scalar(select(func.count(model.id)))
        recent = await uow.session.scalar(
            select(func.count(model.id)).where(model.created_at >= since)
        )
    return {"total": int(total or 0), "window_increment": int(recent or 0)}
