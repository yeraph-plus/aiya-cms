"""Read-only gift-card queries."""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import Any

from sqlalchemy import select

from inc.capabilities.gift_cards.commands import _batch_dto, _redemption_dto, digest_secret
from inc.capabilities.gift_cards.models import GiftCard, GiftCardBatch, GiftCardRedemption
from inc.capabilities.gift_cards.schemas import (
    GiftCardBatchDTO,
    GiftCardDTO,
    GiftCardVerifyDTO,
    RedemptionDTO,
)
from inc.kernel.db import Page, UoWFactory, fetch_page
from inc.kernel.time import SYSTEM_CLOCK, Clock


class GiftCardQueries:
    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        secret_pepper: str | bytes,
        clock: Clock | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._secret_pepper = secret_pepper
        self._clock = clock

    async def list_batches(
        self,
        *,
        page: int,
        size: int,
        platform_key: str | None = None,
        product_key: str | None = None,
        status: str | None = None,
    ) -> Page[GiftCardBatchDTO]:
        async with self._uow_factory() as uow:
            statement = select(GiftCardBatch)
            if platform_key:
                statement = statement.where(GiftCardBatch.platform_key == platform_key)
            if product_key:
                statement = statement.where(GiftCardBatch.product_key == product_key)
            if status:
                statement = statement.where(GiftCardBatch.status == status)
            statement = statement.order_by(GiftCardBatch.created_at.desc(), GiftCardBatch.id.desc())
            result = await fetch_page(uow.session, statement, page=page, size=size)
            return Page(
                items=[await _batch_dto(uow, row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )
        raise AssertionError("gift card batch query exited without returning")

    async def get_batch(self, batch_id: str) -> GiftCardBatchDTO | None:
        async with self._uow_factory() as uow:
            row = await uow.session.get(GiftCardBatch, uuid.UUID(str(batch_id)))
            return await _batch_dto(uow, row) if row else None
        raise AssertionError("gift card batch lookup exited without returning")

    async def list_cards(self, *, batch_id: str, page: int, size: int) -> Page[GiftCardDTO]:
        async with self._uow_factory() as uow:
            statement = (
                select(GiftCard)
                .where(GiftCard.batch_id == uuid.UUID(str(batch_id)))
                .order_by(GiftCard.created_at, GiftCard.id)
            )
            result = await fetch_page(uow.session, statement, page=page, size=size)
            return Page(
                items=[_card_dto(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )
        raise AssertionError("gift card list query exited without returning")

    async def get_redemption(self, redemption_id: str) -> RedemptionDTO | None:
        async with self._uow_factory() as uow:
            row = await uow.session.get(GiftCardRedemption, uuid.UUID(str(redemption_id)))
            return _redemption_dto(row) if row else None
        raise AssertionError("gift card redemption lookup exited without returning")

    async def verify(
        self, *, secret: str, platform_key: str = "card_platform"
    ) -> GiftCardVerifyDTO:
        """Verify an internal card without creating a redemption or writing state."""

        digest = digest_secret(secret, self._secret_pepper, platform_key)
        async with self._uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(GiftCard).where(
                            GiftCard.secret_digest == digest,
                            GiftCard.platform_key == platform_key,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                return GiftCardVerifyDTO(valid=False, reason="invalid")
            batch = await uow.session.get(GiftCardBatch, row.batch_id)
            if batch is None:
                return GiftCardVerifyDTO(valid=False, reason="invalid")
            expires_at = _utc(batch.expires_at)
            now = (self._clock or SYSTEM_CLOCK).utc_now()
            if expires_at is not None and expires_at <= _utc(now):
                return GiftCardVerifyDTO(valid=False, reason="expired")
            if row.status != "issued":
                reason = {
                    "reserved": "reserved",
                    "redeemed": "already_redeemed",
                    "revoked": "revoked",
                    "expired": "expired",
                }.get(row.status, "invalid")
                return GiftCardVerifyDTO(valid=False, reason=reason)
            return GiftCardVerifyDTO(
                valid=True,
                platform_key=platform_key,
                product_key=batch.product_key,
                fulfillment_schema_version=batch.fulfillment_schema_version,
                fulfillment_key=batch.fulfillment_key,
                expires_at=expires_at,
            )
        raise AssertionError("gift card verification exited without returning")


def _utc(value: Any) -> Any:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _card_dto(row: GiftCard) -> GiftCardDTO:
    return GiftCardDTO(
        id=str(row.id),
        batch_id=str(row.batch_id),
        platform_key=row.platform_key,
        status=row.status,
        redemption_id=str(row.redemption_id) if row.redemption_id else None,
        reserved_until=_utc(row.reserved_until),
        redeemed_at=_utc(row.redeemed_at),
        revoked_at=_utc(row.revoked_at),
        created_at=_utc(row.created_at),
        version=row.version,
    )
