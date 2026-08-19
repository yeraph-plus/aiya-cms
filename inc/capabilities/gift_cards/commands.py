"""Semantic gift-card commands and the redemption state machine."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select

from inc.capabilities.gift_cards.events import GIFT_CARD_EVENT_SCHEMAS
from inc.capabilities.gift_cards.models import (
    GiftCard,
    GiftCardBatch,
    GiftCardExternalClaim,
    GiftCardRedemption,
)
from inc.capabilities.gift_cards.ports import (
    GiftCardPlatformPort,
    GiftCardProviderError,
    GiftCardSettingsSnapshot,
    GiftCardWebhookRequest,
    ProviderPurchaseFact,
)
from inc.capabilities.gift_cards.schemas import (
    CancelGiftCardRedemptionInput,
    CloseGiftCardBatchInput,
    CommitGiftCardRedemptionInput,
    FulfillmentPayload,
    GenerateGiftCardBatchInput,
    GiftCardBatchDTO,
    GiftCardBatchResultDTO,
    GiftCardDTO,
    ProviderPurchaseInput,
    RedemptionDTO,
    ReserveGiftCardRedemptionInput,
    RevokeGiftCardInput,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

PERMISSION_BATCH_GENERATE = "gift_cards.batch_generate"
PERMISSION_MANAGE = "gift_cards.manage"
PERMISSION_VERIFY = "gift_cards.verify"
PERMISSION_REDEEM = "gift_cards.redeem"
PERMISSION_RECONCILE = "gift_cards.reconcile"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    providers: dict[str, GiftCardPlatformPort]
    secret_pepper: str | bytes = "aiya-gift-card-development-pepper"
    default_provider: str = "card_platform"
    provider_settings: dict[str, Any] | None = None
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None
    reserve_ttl_seconds: int = 15 * 60


def digest_secret(secret: str, pepper: str | bytes, platform_key: str = "") -> str:
    """Return the only persisted representation of a card secret."""

    key = pepper.encode("utf-8") if isinstance(pepper, str) else pepper
    if not key:
        raise ValueError("gift card secret pepper cannot be empty")
    return hmac.new(key, f"{platform_key}\0{secret}".encode(), hashlib.sha256).hexdigest()


def _forbidden(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.FORBIDDEN, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


def _validation(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


def _not_found(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.NOT_FOUND, message=message)


def _require(ctx: CommandContext, key: str) -> None:
    if key not in ctx.permissions:
        raise _forbidden("gift_cards.forbidden", f"requires permission {key}")


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _utc_required(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _payload(key: str, values: dict[str, Any]) -> FulfillmentPayload:
    return FulfillmentPayload(values={"fulfillment_key": key, **values})


def _payload_values(
    row: GiftCardBatch | GiftCardExternalClaim | GiftCardRedemption,
) -> dict[str, Any]:
    return dict(row.fulfillment_payload.values)


def _fulfillment_key(row: GiftCardBatch | GiftCardExternalClaim | GiftCardRedemption) -> str:
    return str(_payload_values(row).get("fulfillment_key", row.fulfillment_key))


async def _batch_dto(uow: UnitOfWork, row: GiftCardBatch) -> GiftCardBatchDTO:
    counts = (
        await uow.session.execute(
            select(GiftCard.status, func.count(GiftCard.id))
            .where(GiftCard.batch_id == row.id)
            .group_by(GiftCard.status)
        )
    ).all()
    by_status = {str(status): int(count) for status, count in counts}
    return GiftCardBatchDTO(
        id=str(row.id),
        batch_key=row.batch_key,
        platform_key=row.platform_key,
        product_key=row.product_key,
        fulfillment_schema_version=row.fulfillment_schema_version,
        fulfillment_key=row.fulfillment_key,
        quantity=row.quantity,
        generated_count=row.generated_count,
        available_count=by_status.get("issued", 0),
        redeemed_count=by_status.get("redeemed", 0),
        revoked_count=by_status.get("revoked", 0),
        expires_at=_utc(row.expires_at),
        status=row.status,
        idempotency_key=row.idempotency_key,
        created_by=row.created_by,
        created_at=_utc(row.created_at),  # type: ignore[arg-type]
        closed_at=_utc(row.closed_at),
    )


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
        created_at=_utc(row.created_at),  # type: ignore[arg-type]
        version=row.version,
    )


def _redemption_dto(row: GiftCardRedemption) -> RedemptionDTO:
    values = _payload_values(row)
    return RedemptionDTO(
        id=str(row.id),
        source_kind=row.source_kind,  # type: ignore[arg-type]
        source_id=row.source_id,
        platform_key=row.platform_key,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        fulfillment_schema_version=row.fulfillment_schema_version,
        fulfillment_key=row.fulfillment_key,
        fulfillment_payload=values,
        status=row.status,
        idempotency_key=row.idempotency_key,
        reserved_until=_utc(row.reserved_until),
        committed_at=_utc(row.committed_at),
        cancelled_at=_utc(row.cancelled_at),
        created_at=_utc(row.created_at),  # type: ignore[arg-type]
    )


async def _emit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    key: str,
    aggregate_type: str,
    aggregate_id: str,
    platform_key: str,
    product_key: str,
    **values: Any,
) -> None:
    payload = GIFT_CARD_EVENT_SCHEMAS[key].model_validate(
        {"platform_key": platform_key, "product_key": product_key, **values}
    )
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=key,
            occurred_at=ctx.clock.utc_now(),
            producer="gift_cards",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            trace_id=ctx.trace_id,
            payload=payload.model_dump(mode="json"),
        ),
    )


class GenerateGiftCardBatch:
    """Generate a fixed-size batch; plaintext secrets are returned once."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: GenerateGiftCardBatchInput) -> GiftCardBatchResultDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_BATCH_GENERATE)
        async with ctx.uow_factory() as uow:
            existing = (
                (
                    await uow.session.execute(
                        select(GiftCardBatch).where(
                            GiftCardBatch.idempotency_key == input_.idempotency_key
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                return GiftCardBatchResultDTO(batch=await _batch_dto(uow, existing), secrets=None)

            now = ctx.clock.utc_now()
            expires_at = _utc(input_.expires_at)
            if expires_at is not None and expires_at <= now:
                raise _validation("gift_cards.expiry_in_past", "expiry must be in the future")
            batch = GiftCardBatch(
                batch_key=input_.batch_key or f"batch_{secrets.token_urlsafe(12)}",
                platform_key=input_.platform_key,
                product_key=input_.product_key,
                fulfillment_schema_version=input_.fulfillment_schema_version,
                fulfillment_key=input_.fulfillment_key,
                fulfillment_payload=_payload(input_.fulfillment_key, input_.fulfillment_payload),
                quantity=input_.quantity,
                generated_count=input_.quantity,
                expires_at=expires_at,
                status="active",
                idempotency_key=input_.idempotency_key,
                created_by=ctx.actor_id,
            )
            uow.session.add(batch)
            await uow.session.flush()
            plaintext: list[str] = []
            seen: set[str] = set()
            while len(plaintext) < input_.quantity:
                secret = secrets.token_urlsafe(24)
                digest = digest_secret(secret, ctx.secret_pepper, input_.platform_key)
                if digest in seen:
                    continue
                seen.add(digest)
                plaintext.append(secret)
                uow.session.add(
                    GiftCard(
                        batch_id=batch.id,
                        platform_key=input_.platform_key,
                        secret_digest=digest,
                        status="issued",
                        version=1,
                    )
                )
            await _emit(
                ctx,
                uow,
                key="gift_cards.batch_created.v1",
                aggregate_type="gift_card_batch",
                aggregate_id=str(batch.id),
                platform_key=batch.platform_key,
                product_key=batch.product_key,
                batch_id=str(batch.id),
                batch_key=batch.batch_key,
                quantity=batch.quantity,
                expires_at=batch.expires_at,
            )
            await uow.session.flush()
            result = GiftCardBatchResultDTO(batch=await _batch_dto(uow, batch), secrets=plaintext)
            await uow.commit()
            return result
        raise AssertionError("gift card batch generation exited without returning")


class CloseGiftCardBatch:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: CloseGiftCardBatchInput) -> GiftCardBatchDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_MANAGE)
        async with ctx.uow_factory() as uow:
            row = await uow.session.get(GiftCardBatch, uuid.UUID(str(input_.batch_id)))
            if row is None:
                raise _not_found("gift_cards.batch_not_found", "gift card batch not found")
            if row.status == "closed":
                return await _batch_dto(uow, row)
            if row.status != "active":
                raise _conflict("gift_cards.batch_closed", "gift card batch cannot be closed")
            row.status = "closed"
            row.closed_at = ctx.clock.utc_now()
            await _emit(
                ctx,
                uow,
                key="gift_cards.batch_closed.v1",
                aggregate_type="gift_card_batch",
                aggregate_id=str(row.id),
                platform_key=row.platform_key,
                product_key=row.product_key,
                batch_id=str(row.id),
                reason=input_.reason,
            )
            await uow.commit()
            return await _batch_dto(uow, row)
        raise AssertionError("gift card batch close exited without returning")


class RevokeGiftCard:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: RevokeGiftCardInput) -> GiftCardDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_MANAGE)
        async with ctx.uow_factory() as uow:
            row = await uow.session.get(GiftCard, uuid.UUID(str(input_.card_id)))
            if row is None:
                raise _not_found("gift_cards.card_not_found", "gift card not found")
            if row.version != input_.expected_version:
                raise _conflict("gift_cards.redemption_conflict", "gift card version changed")
            if row.status == "revoked":
                return _card_dto(row)
            if row.status != "issued":
                raise _conflict("gift_cards.already_redeemed", "gift card is not available")
            row.status = "revoked"
            row.revoked_at = ctx.clock.utc_now()
            row.version += 1
            batch = await uow.session.get(GiftCardBatch, row.batch_id)
            if batch is None:
                raise _not_found("gift_cards.batch_not_found", "gift card batch not found")
            await _emit(
                ctx,
                uow,
                key="gift_cards.card_revoked.v1",
                aggregate_type="gift_card",
                aggregate_id=str(row.id),
                platform_key=row.platform_key,
                product_key=batch.product_key,
                card_id=str(row.id),
                batch_id=str(batch.id),
                reason=input_.reason,
            )
            await uow.commit()
            return _card_dto(row)
        raise AssertionError("gift card revoke exited without returning")


async def _find_internal(
    uow: UnitOfWork, *, secret_digest: str, platform_key: str
) -> GiftCard | None:
    result = await uow.session.execute(
        select(GiftCard)
        .where(
            GiftCard.secret_digest == secret_digest,
            GiftCard.platform_key == platform_key,
        )
        .with_for_update()
    )
    return cast(GiftCard | None, result.scalars().first())


async def _expire_if_needed(
    ctx: CommandContext, uow: UnitOfWork, card: GiftCard, batch: GiftCardBatch
) -> None:
    now = ctx.clock.utc_now()
    if (
        card.status in ("issued", "reserved")
        and batch.expires_at is not None
        and _utc_required(batch.expires_at) <= now
    ):
        card.status = "expired"
        card.version += 1
        raise _conflict("gift_cards.expired", "gift card has expired")


class ReserveGiftCardRedemption:
    """Atomically reserve an internal card or a verified external claim."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: ReserveGiftCardRedemptionInput) -> RedemptionDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_REDEEM)
        platform_key = input_.platform_key or ctx.default_provider

        # Idempotency is checked before any provider call.
        async with ctx.uow_factory() as read_uow:
            replay = (
                (
                    await read_uow.session.execute(
                        select(GiftCardRedemption).where(
                            GiftCardRedemption.platform_key == platform_key,
                            GiftCardRedemption.idempotency_key == input_.idempotency_key,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if replay is not None:
                if (
                    replay.subject_type != input_.subject_type
                    or replay.subject_id != input_.subject_id
                ):
                    raise _conflict(
                        "gift_cards.idempotency_conflict",
                        "idempotency key belongs to another subject",
                    )
                return _redemption_dto(replay)

        digest = digest_secret(input_.secret, ctx.secret_pepper, platform_key)
        fact: ProviderPurchaseFact | None = None
        async with ctx.uow_factory() as uow:
            card = await _find_internal(uow, secret_digest=digest, platform_key=platform_key)
            if card is not None:
                batch = await uow.session.get(GiftCardBatch, card.batch_id)
                if batch is None:
                    raise _not_found("gift_cards.batch_not_found", "gift card batch not found")
                await _expire_if_needed(ctx, uow, card, batch)
                if card.status == "redeemed":
                    raise _conflict("gift_cards.already_redeemed", "gift card already redeemed")
                if card.status == "revoked":
                    raise _conflict("gift_cards.revoked", "gift card has been revoked")
                if card.status == "reserved":
                    if (
                        card.reserved_until
                        and _utc_required(card.reserved_until) <= ctx.clock.utc_now()
                    ):
                        card.status = "issued"
                        card.redemption_id = None
                        card.reserved_until = None
                        card.version += 1
                    else:
                        raise _conflict("gift_cards.redemption_conflict", "gift card is reserved")
                if card.status != "issued":
                    raise _conflict("gift_cards.invalid_secret", "gift card is not valid")
                redemption = GiftCardRedemption(
                    source_kind="internal",
                    source_id=str(card.id),
                    platform_key=platform_key,
                    subject_type=input_.subject_type,
                    subject_id=input_.subject_id,
                    fulfillment_schema_version=batch.fulfillment_schema_version,
                    fulfillment_key=batch.fulfillment_key,
                    fulfillment_payload=batch.fulfillment_payload,
                    status="reserved",
                    idempotency_key=input_.idempotency_key,
                    reserved_until=ctx.clock.utc_now() + timedelta(seconds=ctx.reserve_ttl_seconds),
                )
                uow.session.add(redemption)
                await uow.session.flush()
                card.status = "reserved"
                card.redemption_id = redemption.id
                card.reserved_until = redemption.reserved_until
                card.version += 1
                await _emit(
                    ctx,
                    uow,
                    key="gift_cards.redemption_reserved.v1",
                    aggregate_type="gift_card_redemption",
                    aggregate_id=str(redemption.id),
                    platform_key=platform_key,
                    product_key=batch.product_key,
                    redemption_id=str(redemption.id),
                    source_kind="internal",
                    source_id=str(card.id),
                    subject_type=redemption.subject_type,
                    subject_id=redemption.subject_id,
                    status=redemption.status,
                )
                await uow.commit()
                return _redemption_dto(redemption)

        provider = ctx.providers.get(platform_key)
        if provider is None:
            if platform_key != "card_platform":
                raise GiftCardProviderError()
            raise _validation("gift_cards.invalid_secret", "gift card is not valid")
        try:
            fact = await provider.lookup_purchase(
                input_.secret,
                {"platform_key": platform_key},
                GiftCardSettingsSnapshot((ctx.provider_settings or {}).get(platform_key, {})),
            )
        except KernelError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider details never cross the boundary
            raise GiftCardProviderError() from exc
        if not fact.paid:
            raise _conflict("gift_cards.provider_not_paid", "provider purchase is not paid")
        external_digest = digest_secret(fact.external_order_id, ctx.secret_pepper, platform_key)
        fact_digest = hashlib.sha256(fact.provider_fact_id.encode("utf-8")).hexdigest()
        async with ctx.uow_factory() as uow:
            claim = (
                (
                    await uow.session.execute(
                        select(GiftCardExternalClaim).where(
                            GiftCardExternalClaim.platform_key == platform_key,
                            GiftCardExternalClaim.external_order_digest == external_digest,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if claim is None:
                claim = GiftCardExternalClaim(
                    platform_key=platform_key,
                    external_order_digest=external_digest,
                    product_key=fact.product_key,
                    fulfillment_schema_version=fact.fulfillment_schema_version,
                    fulfillment_key=fact.fulfillment_key,
                    fulfillment_payload=_payload(fact.fulfillment_key, fact.fulfillment_payload),
                    provider_fact_digest=fact_digest,
                    provider_status="paid",
                    verified_at=ctx.clock.utc_now(),
                    expires_at=_utc(fact.expires_at),
                )
                uow.session.add(claim)
                await uow.session.flush()
            elif claim.redemption_id is not None:
                raise _conflict("gift_cards.already_redeemed", "provider purchase already redeemed")
            if (
                claim.expires_at is not None
                and _utc_required(claim.expires_at) <= ctx.clock.utc_now()
            ):
                raise _conflict("gift_cards.expired", "provider purchase has expired")
            if claim.product_key != fact.product_key:
                raise _conflict(
                    "gift_cards.product_not_eligible", "provider product is not eligible"
                )
            redemption = GiftCardRedemption(
                source_kind="external",
                source_id=str(claim.id),
                platform_key=platform_key,
                subject_type=input_.subject_type,
                subject_id=input_.subject_id,
                fulfillment_schema_version=claim.fulfillment_schema_version,
                fulfillment_key=claim.fulfillment_key,
                fulfillment_payload=claim.fulfillment_payload,
                status="reserved",
                idempotency_key=input_.idempotency_key,
                reserved_until=ctx.clock.utc_now() + timedelta(seconds=ctx.reserve_ttl_seconds),
            )
            uow.session.add(redemption)
            await uow.session.flush()
            claim.redemption_id = redemption.id
            await _emit(
                ctx,
                uow,
                key="gift_cards.redemption_reserved.v1",
                aggregate_type="gift_card_redemption",
                aggregate_id=str(redemption.id),
                platform_key=platform_key,
                product_key=claim.product_key,
                redemption_id=str(redemption.id),
                source_kind="external",
                source_id=str(claim.id),
                subject_type=redemption.subject_type,
                subject_id=redemption.subject_id,
                status=redemption.status,
            )
            await uow.commit()
            return _redemption_dto(redemption)

        raise AssertionError("gift card redemption reservation exited without returning")


class CommitGiftCardRedemption:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: CommitGiftCardRedemptionInput) -> RedemptionDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_REDEEM)
        async with ctx.uow_factory() as uow:
            row = await uow.session.get(GiftCardRedemption, uuid.UUID(str(input_.redemption_id)))
            if row is None:
                raise _not_found("gift_cards.redemption_not_found", "redemption not found")
            if row.status == "committed":
                if row.idempotency_key != input_.idempotency_key:
                    raise _conflict(
                        "gift_cards.idempotency_conflict", "redemption idempotency key differs"
                    )
                return _redemption_dto(row)
            if row.status != "reserved":
                raise _conflict("gift_cards.redemption_conflict", "redemption is not reserved")
            if row.reserved_until and _utc_required(row.reserved_until) <= ctx.clock.utc_now():
                row.status = "expired"
                raise _conflict("gift_cards.expired", "redemption reservation expired")
            if row.idempotency_key != input_.idempotency_key:
                raise _conflict(
                    "gift_cards.idempotency_conflict", "redemption idempotency key differs"
                )
            row.status = "committed"
            row.committed_at = ctx.clock.utc_now()
            if row.source_kind == "internal":
                card = await uow.session.get(GiftCard, uuid.UUID(row.source_id))
                if card is None:
                    raise _not_found("gift_cards.card_not_found", "gift card not found")
                card.status = "redeemed"
                card.redeemed_at = row.committed_at
                card.reserved_until = None
                card.version += 1
            else:
                claim = await uow.session.get(GiftCardExternalClaim, uuid.UUID(row.source_id))
                if claim is not None:
                    claim.redemption_id = row.id
            product_key = "external"
            if row.source_kind == "internal":
                card = await uow.session.get(GiftCard, uuid.UUID(row.source_id))
                batch = await uow.session.get(GiftCardBatch, card.batch_id) if card else None
                product_key = batch.product_key if batch else "internal"
            await _emit(
                ctx,
                uow,
                key="gift_cards.redemption_committed.v1",
                aggregate_type="gift_card_redemption",
                aggregate_id=str(row.id),
                platform_key=row.platform_key,
                product_key=product_key,
                redemption_id=str(row.id),
                source_kind=row.source_kind,
                source_id=row.source_id,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                status=row.status,
            )
            await uow.commit()
            return _redemption_dto(row)

        raise AssertionError("gift card redemption commit exited without returning")


class CancelGiftCardRedemption:
    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: CancelGiftCardRedemptionInput) -> RedemptionDTO:
        ctx = self._ctx
        _require(ctx, PERMISSION_REDEEM)
        async with ctx.uow_factory() as uow:
            row = await uow.session.get(GiftCardRedemption, uuid.UUID(str(input_.redemption_id)))
            if row is None:
                raise _not_found("gift_cards.redemption_not_found", "redemption not found")
            if row.status == "cancelled":
                return _redemption_dto(row)
            if row.status != "reserved":
                raise _conflict(
                    "gift_cards.redemption_conflict", "committed redemption cannot be cancelled"
                )
            row.status = "cancelled"
            row.cancelled_at = ctx.clock.utc_now()
            if row.source_kind == "internal":
                card = await uow.session.get(GiftCard, uuid.UUID(row.source_id))
                if card is not None and card.status == "reserved":
                    card.status = "issued"
                    card.redemption_id = None
                    card.reserved_until = None
                    card.version += 1
            else:
                claim = await uow.session.get(GiftCardExternalClaim, uuid.UUID(row.source_id))
                if claim is not None:
                    claim.redemption_id = None
            await _emit(
                ctx,
                uow,
                key="gift_cards.redemption_cancelled.v1",
                aggregate_type="gift_card_redemption",
                aggregate_id=str(row.id),
                platform_key=row.platform_key,
                product_key="external" if row.source_kind == "external" else "internal",
                redemption_id=str(row.id),
                source_kind=row.source_kind,
                source_id=row.source_id,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                status=row.status,
            )
            await uow.commit()
            return _redemption_dto(row)

        raise AssertionError("gift card redemption cancellation exited without returning")


class RecordProviderPurchase:
    """Record a verified provider fact exactly once (no raw order persisted)."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: ProviderPurchaseInput) -> dict[str, Any]:
        ctx = self._ctx
        _require(ctx, PERMISSION_RECONCILE)
        if not input_.paid:
            raise _conflict("gift_cards.provider_not_paid", "provider purchase is not paid")
        external_digest = digest_secret(
            input_.external_order_id, ctx.secret_pepper, input_.platform_key
        )
        fact_digest = hashlib.sha256(input_.provider_fact_id.encode("utf-8")).hexdigest()
        async with ctx.uow_factory() as uow:
            existing = (
                (
                    await uow.session.execute(
                        select(GiftCardExternalClaim).where(
                            GiftCardExternalClaim.platform_key == input_.platform_key,
                            GiftCardExternalClaim.external_order_digest == external_digest,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                return {"duplicate": True, "claim_id": str(existing.id), "allocated_card_ids": []}
            claim = GiftCardExternalClaim(
                platform_key=input_.platform_key,
                external_order_digest=external_digest,
                product_key=input_.product_key,
                fulfillment_schema_version=input_.fulfillment_schema_version,
                fulfillment_key=input_.fulfillment_key,
                fulfillment_payload=_payload(input_.fulfillment_key, input_.fulfillment_payload),
                provider_fact_digest=fact_digest,
                provider_status="paid",
                verified_at=ctx.clock.utc_now(),
                expires_at=_utc(input_.expires_at),
            )
            uow.session.add(claim)
            await uow.session.flush()
            allocated: list[str] = []
            if input_.batch_id:
                cards = (
                    (
                        await uow.session.execute(
                            select(GiftCard)
                            .join(GiftCardBatch, GiftCard.batch_id == GiftCardBatch.id)
                            .where(
                                GiftCard.batch_id == uuid.UUID(input_.batch_id),
                                GiftCard.status == "issued",
                                GiftCardBatch.product_key == input_.product_key,
                            )
                            .limit(input_.quantity)
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(cards) != input_.quantity:
                    raise _conflict(
                        "gift_cards.product_not_eligible", "batch has insufficient available cards"
                    )
                allocated = [str(card.id) for card in cards]
            await _emit(
                ctx,
                uow,
                key="gift_cards.provider_purchase_recorded.v1",
                aggregate_type="gift_card_external_claim",
                aggregate_id=str(claim.id),
                platform_key=claim.platform_key,
                product_key=claim.product_key,
                claim_id=str(claim.id),
                provider_fact_digest=claim.provider_fact_digest,
                external_order_digest=claim.external_order_digest,
                quantity=input_.quantity,
            )
            await uow.commit()
            return {"duplicate": False, "claim_id": str(claim.id), "allocated_card_ids": allocated}
        raise AssertionError("provider purchase recording exited without returning")


class RecordProviderWebhook:
    """Verify a provider callback before recording its normalized fact."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(
        self, *, provider_key: str, request: GiftCardWebhookRequest
    ) -> dict[str, Any]:
        ctx = self._ctx
        _require(ctx, PERMISSION_RECONCILE)
        provider = ctx.providers.get(provider_key)
        if provider is None:
            raise _validation("gift_cards.unknown_provider", "gift card provider is not configured")
        try:
            fact = await provider.verify_webhook(
                request,
                GiftCardSettingsSnapshot((ctx.provider_settings or {}).get(provider_key, {})),
            )
        except KernelError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise KernelError(
                code="gift_cards.webhook_invalid",
                category=ErrorCategory.VALIDATION,
                message="provider webhook could not be verified",
            ) from exc
        result = await RecordProviderPurchase(ctx)(
            ProviderPurchaseInput(
                platform_key=fact.platform_key,
                external_order_id=fact.external_order_id,
                provider_fact_id=fact.provider_fact_id,
                paid=fact.paid,
                product_key=fact.product_key,
                fulfillment_schema_version=fact.fulfillment_schema_version,
                fulfillment_key=fact.fulfillment_key,
                fulfillment_payload=fact.fulfillment_payload,
                occurred_at=fact.occurred_at,
                expires_at=fact.expires_at,
                idempotency_key=fact.idempotency_key or fact.provider_fact_id,
                quantity=fact.quantity,
            )
        )
        await provider.acknowledge_webhook(
            fact, GiftCardSettingsSnapshot((ctx.provider_settings or {}).get(provider_key, {}))
        )
        return result
