"""Lightweight capability diagnostics."""

from __future__ import annotations

from sqlalchemy import func, select

from inc.capabilities.gift_cards.models import GiftCard, GiftCardBatch
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus
from inc.kernel.time import Clock


class GiftCardDiagnostics:
    key = "gift_cards"

    def __init__(self, *, uow_factory: UoWFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def run(self) -> list[DiagnosticResult]:
        now = self._clock.utc_now()
        async with self._uow_factory() as uow:
            expired = int(
                (
                    await uow.session.execute(
                        select(func.count(GiftCard.id))
                        .join(GiftCardBatch, GiftCard.batch_id == GiftCardBatch.id)
                        .where(
                            GiftCard.status.in_(("issued", "reserved")),
                            GiftCardBatch.expires_at.is_not(None),
                            GiftCardBatch.expires_at <= now,
                        )
                    )
                ).scalar_one()
            )
        return [
            DiagnosticResult(
                code="gift_cards.expired_pending",
                status=DiagnosticStatus.DEGRADED if expired else DiagnosticStatus.OK,
                summary=f"{expired} issued or reserved cards past their expiry",
            )
        ]
