"""Dashboard summary provider for gift-card batches."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from inc.capabilities.gift_cards.models import GiftCard, GiftCardBatch
from inc.kernel.db import UoWFactory
from inc.kernel.time import Clock


class Provider:
    key = "gift_cards"

    def __init__(self, *, uow_factory: UoWFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def summary(self) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            batches = int(
                (await uow.session.execute(select(func.count(GiftCardBatch.id)))).scalar_one()
            )
            cards = int((await uow.session.execute(select(func.count(GiftCard.id)))).scalar_one())
            available = int(
                (
                    await uow.session.execute(
                        select(func.count(GiftCard.id)).where(GiftCard.status == "issued")
                    )
                ).scalar_one()
            )
        return {"batches": batches, "cards": cards, "available_cards": available}
