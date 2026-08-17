"""Membership commands.

Contract source: context/spec/capabilities/membership.md §4/§5.

Subscribe/renew grant points through the PointsLedger Port into points'
expiring buckets (expires_at = cycle end). Membership never settles
remaining quota itself: expiry of the bucket is points' job. All commands
are idempotent by key where a retry could double-apply.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from inc.capabilities.membership.events import MEMBERSHIP_EVENT_SCHEMAS
from inc.capabilities.membership.levels import MembershipLevelRegistry, MembershipLevelSpec
from inc.capabilities.membership.models import (
    MembershipLevel,
    MembershipRenewalRecord,
    MembershipSubscription,
)
from inc.capabilities.membership.ports import PointsLedgerPort, SubjectExistsPort
from inc.capabilities.membership.schemas import (
    CancelInput,
    RenewInput,
    SubscribeInput,
    SubscriptionDTO,
    TerminateInput,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

PERMISSION_MANAGE = "membership.manage"
GRANT_SOURCE_TYPE = "membership"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    levels: MembershipLevelRegistry
    subject_exists: SubjectExistsPort
    points_ledger: PointsLedgerPort
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None


def _forbidden(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.FORBIDDEN, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.CONFLICT, message=message)


def _validation(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


def _not_found(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.NOT_FOUND, message=message)


def _require_permission(ctx: CommandContext, key: str) -> None:
    if key not in ctx.permissions:
        raise _forbidden("membership.forbidden", f"requires permission {key}")


def _ensure_utc(value: Any) -> Any:
    from datetime import UTC

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def _require_level(ctx: CommandContext, key: str) -> MembershipLevelSpec:
    try:
        return ctx.levels.require(key)
    except KernelError as exc:
        if exc.code != "membership.unknown_level":
            raise
        async with ctx.uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(MembershipLevel).where(MembershipLevel.level_key == key)
                    )
                )
                .scalars()
                .first()
            )
        if row is None:
            raise _validation("membership.unknown_level", exc.message) from exc
        spec = MembershipLevelSpec(
            key=row.level_key,
            display_name=row.display_name,
            tier_rank=row.tier_rank,
            cycle_days=row.cycle_days,
            grant_points=row.grant_points,
            renewal_allowed=row.renewal_allowed,
            status=row.status,
            version=row.version,
        )
        ctx.levels.register_runtime(spec)
        return spec


async def _emit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    key: str,
    subscription: MembershipSubscription,
    **values: Any,
) -> None:
    await ctx.outbox.append(
        uow,
        EventEnvelope(
            event_id=uuid.uuid7(),
            event_key=key,
            occurred_at=ctx.clock.utc_now(),
            producer="membership",
            aggregate_type="membership",
            aggregate_id=str(subscription.id),
            trace_id=ctx.trace_id,
            payload=MEMBERSHIP_EVENT_SCHEMAS[key]
            .model_validate(
                {
                    "subscription_id": str(subscription.id),
                    "subject_type": subscription.subject_type,
                    "subject_id": subscription.subject_id,
                    **values,
                }
            )
            .model_dump(mode="json"),
        ),
    )


def _to_subscription(row: MembershipSubscription) -> SubscriptionDTO:
    return SubscriptionDTO(
        id=str(row.id),
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        level_key=row.level_key,
        cycle_start=_ensure_utc(row.cycle_start),
        cycle_end=_ensure_utc(row.cycle_end),
        status=row.status,
        auto_renew=row.auto_renew,
        granted_points=row.granted_points,
        renewal_count=row.renewal_count,
        cancelled_at=_ensure_utc(row.cancelled_at) if row.cancelled_at else None,
        expired_at=_ensure_utc(row.expired_at) if row.expired_at else None,
    )


def _grant_key(subscription_id: Any, cycle_end: Any) -> str:
    return f"membership:grant:{subscription_id}:{cycle_end.isoformat()}"


def _source_ref(subscription_id: Any, cycle_end: Any) -> str:
    return f"membership:{subscription_id}:{cycle_end.isoformat()}"


async def _grant(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    subscription: MembershipSubscription,
    level: MembershipLevelSpec,
) -> tuple[str, str]:
    """Grant the cycle quota into points; returns (source_ref, entry_id)."""

    source_ref = _source_ref(subscription.id, subscription.cycle_end)
    transactional_grant = getattr(ctx.points_ledger, "grant_points_in_uow", None)
    if transactional_grant is not None:
        result = await transactional_grant(
            uow,
            subject_type=subscription.subject_type,
            subject_id=subscription.subject_id,
            amount=level.grant_points,
            expires_at=subscription.cycle_end,
            idempotency_key=_grant_key(subscription.id, subscription.cycle_end),
            source_ref=source_ref,
        )
    else:
        result = await ctx.points_ledger.grant_points(
            subject_type=subscription.subject_type,
            subject_id=subscription.subject_id,
            amount=level.grant_points,
            expires_at=subscription.cycle_end,
            idempotency_key=_grant_key(subscription.id, subscription.cycle_end),
            source_ref=source_ref,
        )
    entry_id = str(result.get("entry_id") or "")
    if not entry_id:
        raise KernelError(
            code="membership.points_grant_invalid",
            category=ErrorCategory.INTERNAL,
            message="points ledger did not return an entry id",
        )
    uow.session.add(
        MembershipRenewalRecord(
            subscription_id=subscription.id,
            cycle_start=subscription.cycle_start,
            cycle_end=subscription.cycle_end,
            granted_points=level.grant_points,
            points_source_id=source_ref,
            points_entry_id=uuid.UUID(entry_id),
            outcome="granted",
        )
    )
    return source_ref, entry_id


class SubscribeLevel:
    """Open (or switch) a subscription for a subject and grant the cycle quota."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, input_: SubscribeInput
    ) -> SubscriptionDTO:
        ctx = self._ctx
        if not await ctx.subject_exists(input_.subject_type, input_.subject_id):
            raise _validation(
                "membership.subject_not_found",
                f"subject {input_.subject_type}:{input_.subject_id} does not exist",
            )
        level = await _require_level(ctx, input_.level_key)
        if level.status != "active":
            raise _conflict("membership.level_inactive", f"level {level.key} is {level.status}")
        async with ctx.uow_factory() as uow:
            existing = await _find_subscription(uow, input_.subject_type, input_.subject_id)
            if existing is not None:
                if (
                    existing.status == "active"
                    and existing.level_key == level.key
                    and _ensure_utc(existing.cycle_end) > ctx.clock.utc_now()
                ):
                    # same level already active: idempotent replay returns it
                    await uow.commit()
                    return _to_subscription(existing)
                if existing.status in ("active", "cancelled"):
                    # switch level or resume after cancellation: end the
                    # current cycle now; the granted quota keeps its own
                    # expiry and is never settled here.
                    existing.status = "expired"
                    existing.expired_at = ctx.clock.utc_now()
            now = ctx.clock.utc_now()
            cycle_end = now + timedelta(days=level.cycle_days)
            if existing is None:
                subscription = MembershipSubscription(
                    subject_type=input_.subject_type,
                    subject_id=input_.subject_id,
                    level_key=level.key,
                    cycle_start=now,
                    cycle_end=cycle_end,
                    status="active",
                    auto_renew=input_.auto_renew,
                    granted_points=level.grant_points,
                    renewal_count=0,
                )
                uow.session.add(subscription)
                await uow.session.flush()
            else:
                subscription = existing
                subscription.level_key = level.key
                subscription.cycle_start = now
                subscription.cycle_end = cycle_end
                subscription.status = "active"
                subscription.auto_renew = input_.auto_renew
                subscription.granted_points = level.grant_points
                subscription.renewal_count += 1
                subscription.cancelled_at = None
                subscription.expired_at = None
            await _grant(ctx, uow, subscription=subscription, level=level)
            await _emit(
                ctx,
                uow,
                key="membership.subscribed.v1",
                subscription=subscription,
                level_key=level.key,
                cycle_start=subscription.cycle_start,
                cycle_end=subscription.cycle_end,
                granted_points=level.grant_points,
            )
            await uow.commit()
            return _to_subscription(subscription)


class RenewSubscription:
    """Advance the cycle and grant the next quota (idempotent per cycle)."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, input_: RenewInput
    ) -> SubscriptionDTO:
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            subscription = await _get_subscription(uow, input_.subscription_id)
            level = await _require_level(ctx, subscription.level_key)
            if level.status != "active":
                raise _conflict(
                    "membership.level_inactive",
                    f"level {level.key} is {level.status}",
                )
            if subscription.status != "active":
                raise _conflict(
                    "membership.not_active",
                    f"subscription {subscription.id} is {subscription.status}",
                )
            if not level.renewal_allowed:
                raise _conflict(
                    "membership.renewal_not_allowed",
                    f"level {level.key} does not allow renewal",
                )
            if _ensure_utc(subscription.cycle_end) > ctx.clock.utc_now():
                raise _conflict(
                    "membership.cycle_not_over",
                    "subscription cycle has not ended",
                )
            now = ctx.clock.utc_now()
            subscription.cycle_start = now
            subscription.cycle_end = now + timedelta(days=level.cycle_days)
            subscription.granted_points += level.grant_points
            subscription.renewal_count += 1
            subscription.expired_at = None
            await _grant(ctx, uow, subscription=subscription, level=level)
            await _emit(
                ctx,
                uow,
                key="membership.renewed.v1",
                subscription=subscription,
                level_key=level.key,
                cycle_start=subscription.cycle_start,
                cycle_end=subscription.cycle_end,
                granted_points=level.grant_points,
            )
            await uow.commit()
            return _to_subscription(subscription)


class CancelSubscription:
    """Stop auto-renewal; the current cycle stays valid until its end."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, input_: CancelInput
    ) -> SubscriptionDTO:
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            subscription = await _get_subscription(uow, input_.subscription_id)
            if subscription.status != "active":
                raise _conflict(
                    "membership.not_active",
                    f"subscription {subscription.id} is {subscription.status}",
                )
            subscription.auto_renew = False
            subscription.cancelled_at = ctx.clock.utc_now()
            await _emit(
                ctx,
                uow,
                key="membership.cancelled.v1",
                subscription=subscription,
                level_key=subscription.level_key,
                cycle_end=subscription.cycle_end,
            )
            await uow.commit()
            return _to_subscription(subscription)


class TerminateSubscription:
    """Admin/system termination: end the cycle now, keep granted quota expiry."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(  # type: ignore[return]
        self, input_: TerminateInput
    ) -> SubscriptionDTO:
        ctx = self._ctx
        _require_permission(ctx, PERMISSION_MANAGE)
        async with ctx.uow_factory() as uow:
            subscription = await _get_subscription(uow, input_.subscription_id)
            if subscription.status != "active":
                raise _conflict(
                    "membership.not_active",
                    f"subscription {subscription.id} is {subscription.status}",
                )
            subscription.status = "expired"
            subscription.expired_at = ctx.clock.utc_now()
            subscription.auto_renew = False
            await _emit(
                ctx,
                uow,
                key="membership.terminated.v1",
                subscription=subscription,
                level_key=subscription.level_key,
                cycle_end=subscription.cycle_end,
            )
            await uow.commit()
            return _to_subscription(subscription)


class ExpireSubscription:
    """Cron-driven state convergence: active + ended cycle -> expired.

    Does not touch points: the granted quota in the expiring bucket is
    zeroed by points' own expiration sweep at the same cycle_end instant.
    """

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self) -> list[SubscriptionDTO]:
        ctx = self._ctx
        expired: list[SubscriptionDTO] = []
        async with ctx.uow_factory() as uow:
            due = (
                (
                    await uow.session.execute(
                        select(MembershipSubscription).where(
                            MembershipSubscription.status == "active",
                            MembershipSubscription.cycle_end <= ctx.clock.utc_now(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for subscription in due:
                subscription.status = "expired"
                subscription.expired_at = ctx.clock.utc_now()
                # Keep the member's auto_renew preference so a later
                # re-subscribe can honor it; expiry must not silently discard
                # the stated preference.
                await _emit(
                    ctx,
                    uow,
                    key="membership.expired.v1",
                    subscription=subscription,
                    level_key=subscription.level_key,
                    cycle_end=subscription.cycle_end,
                )
                expired.append(_to_subscription(subscription))
            await uow.commit()
        return expired


async def _find_subscription(
    uow: UnitOfWork, subject_type: str, subject_id: str
) -> MembershipSubscription | None:
    row: MembershipSubscription | None = (
        (
            await uow.session.execute(
                select(MembershipSubscription).where(
                    MembershipSubscription.subject_type == subject_type,
                    MembershipSubscription.subject_id == subject_id,
                )
            )
        )
        .scalars()
        .first()
    )
    return row


async def _get_subscription(uow: UnitOfWork, subscription_id: Any) -> MembershipSubscription:
    row: MembershipSubscription | None = await uow.session.get(
        MembershipSubscription, uuid.UUID(str(subscription_id))
    )
    if row is None:
        raise _not_found("membership.subscription_not_found", f"subscription {subscription_id}")
    return row
