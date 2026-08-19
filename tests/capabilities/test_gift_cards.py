"""Gift-card capability contracts: one-time secrets and redemption state."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.gift_cards.commands import (
    CancelGiftCardRedemption,
    CommandContext,
    CommitGiftCardRedemption,
    GenerateGiftCardBatch,
    ReserveGiftCardRedemption,
)
from inc.capabilities.gift_cards.events import GIFT_CARD_EVENT_SCHEMAS
from inc.capabilities.gift_cards.models import GiftCard, GiftCardBatch, GiftCardRedemption
from inc.capabilities.gift_cards.schemas import (
    CancelGiftCardRedemptionInput,
    CommitGiftCardRedemptionInput,
    GenerateGiftCardBatchInput,
    ReserveGiftCardRedemptionInput,
)
from inc.kernel.db import UoWFactory
from inc.kernel.events import EventSchemaRegistry, OutboxMessage, OutboxWriter


@pytest.fixture
def gift_ctx(uow_factory: UoWFactory, clock: Any) -> CommandContext:
    registry = EventSchemaRegistry()
    for key, schema in GIFT_CARD_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(registry, clock),
        providers={},
        secret_pepper="test-gift-card-pepper",
        permissions=frozenset(
            {
                "gift_cards.batch_generate",
                "gift_cards.manage",
                "gift_cards.verify",
                "gift_cards.redeem",
                "gift_cards.reconcile",
            }
        ),
        actor_id="admin-1",
        trace_id="trace-1",
    )


def batch_input(**overrides: Any) -> GenerateGiftCardBatchInput:
    values: dict[str, Any] = {
        "quantity": 2,
        "product_key": "membership.basic",
        "fulfillment_schema_version": "1",
        "fulfillment_key": "membership.grant",
        "fulfillment_payload": {"level_key": "basic"},
        "idempotency_key": "batch-1",
    }
    values.update(overrides)
    return GenerateGiftCardBatchInput(**values)


async def test_batch_secrets_are_one_time_and_digest_only(
    gift_ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    first = await GenerateGiftCardBatch(gift_ctx)(batch_input())
    replay = await GenerateGiftCardBatch(gift_ctx)(batch_input())
    assert first.secrets and len(first.secrets) == 2
    assert replay.secrets is None
    async with uow_factory() as uow:
        cards = (await uow.session.execute(select(GiftCard))).scalars().all()
        batches = (await uow.session.execute(select(GiftCardBatch))).scalars().all()
        events = (await uow.session.execute(select(OutboxMessage))).scalars().all()
    assert len(cards) == 2
    assert all(secret not in card.secret_digest for card in cards for secret in first.secrets)
    assert len(batches) == 1
    assert all(
        secret not in str(event.envelope.payload) for secret in first.secrets for event in events
    )


async def test_reserve_commit_and_replay_are_idempotent(
    gift_ctx: CommandContext,
) -> None:
    generated = await GenerateGiftCardBatch(gift_ctx)(
        batch_input(quantity=1, idempotency_key="batch-2")
    )
    secret = generated.secrets[0]  # type: ignore[index]
    reserved = await ReserveGiftCardRedemption(gift_ctx)(
        ReserveGiftCardRedemptionInput(
            secret=secret,
            subject_type="identity",
            subject_id="user-1",
            idempotency_key="redeem-1",
        )
    )
    committed = await CommitGiftCardRedemption(gift_ctx)(
        CommitGiftCardRedemptionInput(redemption_id=reserved.id, idempotency_key="redeem-1")
    )
    replay = await CommitGiftCardRedemption(gift_ctx)(
        CommitGiftCardRedemptionInput(redemption_id=reserved.id, idempotency_key="redeem-1")
    )
    assert committed.status == replay.status == "committed"


async def test_cancel_releases_internal_card(
    gift_ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    generated = await GenerateGiftCardBatch(gift_ctx)(
        batch_input(quantity=1, idempotency_key="batch-3")
    )
    reserved = await ReserveGiftCardRedemption(gift_ctx)(
        ReserveGiftCardRedemptionInput(
            secret=generated.secrets[0],  # type: ignore[index]
            subject_type="identity",
            subject_id="user-2",
            idempotency_key="redeem-2",
        )
    )
    await CancelGiftCardRedemption(gift_ctx)(
        CancelGiftCardRedemptionInput(
            redemption_id=reserved.id,
            reason="downstream unavailable",
            idempotency_key="redeem-2",
        )
    )
    async with uow_factory() as uow:
        card = (await uow.session.execute(select(GiftCard))).scalars().one()
        redemption = await uow.session.get(GiftCardRedemption, uuid.UUID(reserved.id))
    assert card.status == "issued"
    assert redemption is not None and redemption.status == "cancelled"
