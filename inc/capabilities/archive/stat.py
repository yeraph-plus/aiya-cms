"""Archive diagnostics provider for the composition root."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from inc.capabilities.archive.models import ArchiveDownloadGrant, ArchiveItem
from inc.kernel.db import UoWFactory
from inc.kernel.time import Clock


class Provider:
    key = "archive"

    def __init__(self, *, uow_factory: UoWFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def summary(self) -> dict[str, Any]:
        del self._clock
        async with self._uow_factory() as uow:
            items = int(
                (await uow.session.execute(select(func.count(ArchiveItem.id)))).scalar_one()
            )
            grants = int(
                (
                    await uow.session.execute(select(func.count(ArchiveDownloadGrant.id)))
                ).scalar_one()
            )
        return {"items": items, "grants": grants}
