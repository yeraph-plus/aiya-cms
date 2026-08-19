"""Membership commands.

Contract source: context/spec/capabilities/membership.md sections 4 and 5.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any, cast

from sqlalchemy import select

from inc.capabilities.membership.events import MEMBERSHIP_EVENT_SCHEMAS
from inc.capabilities.membership.levels import MembershipLevelRegistry, MembershipLevelSpec
from inc.capabilities.membership.models import (
    MembershipCycle,
    MembershipLevel,
    MembershipSubscription,
)
from inc.capabilities.membership.schemas import (
    AttachPointsGrantInput,
    CancelInput,
    MarkCycleFailedInput,
    MembershipCycleDTO,
    PrepareSubscriptionCycleInput,
    SubscriptionDTO,
    TerminateInput,
)
from inc.kernel.db import UnitOfWork, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock

PERMISSION_MANAGE = "membership.subscriptions.manage"


@dataclass(frozen=True, slots=True)
class CommandContext:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    levels: MembershipLevelRegistry
    permissions: frozenset[str] = frozenset()
    actor_id: str | None = None
    trace_id: str | None = None


def _error(code: str, category: ErrorCategory, message: str) -> KernelError:
    return KernelError(code=code, category=category, message=message)


def _conflict(code: str, message: str) -> KernelError:
    return _error(code, ErrorCategory.CONFLICT, message)


def _validation(code: str, message: str) -> KernelError:
    return _error(code, ErrorCategory.VALIDATION, message)


def _not_found(code: str, message: str) -> KernelError:
    return _error(code, ErrorCategory.NOT_FOUND, message)


def _utc(value: Any) -> Any:
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
            cycle_points_amount=row.grant_points,
            renewal_allowed=row.renewal_allowed,
            status=row.status,
            version=row.version,
        )
        ctx.levels.register_runtime(spec)
        return spec
    raise AssertionError("unreachable: unknown membership level lookup completed")


async def _emit(
    ctx: CommandContext,
    uow: UnitOfWork,
    *,
    key: str,
    subscription: MembershipSubscription,
    cycle: MembershipCycle | None = None,
) -> None:
    values: dict[str, Any] = {
        "subscription_id": str(subscription.id),
        "subject_type": subscription.subject_type,
        "subject_id": subscription.subject_id,
        "level_key": subscription.level_key,
        "cycle_start": subscription.cycle_start,
        "cycle_end": subscription.cycle_end,
        "cycle_points_amount": subscription.granted_points,
    }
    if cycle is not None:
        values.update(
            cycle_id=str(cycle.id),
            source_type=cycle.source_type,
            source_ref=cycle.source_ref,
            points_entry_ref=cycle.points_entry_ref,
            failure_code=cycle.failure_code,
        )
    payload = MEMBERSHIP_EVENT_SCHEMAS[key].model_validate(values).model_dump(mode="json")
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
            payload=payload,
        ),
    )


class PrepareSubscriptionCycle:
    """Create a prepared cycle without granting membership entitlement."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: PrepareSubscriptionCycleInput) -> MembershipCycleDTO:
        ctx = self._ctx
        level = await _require_level(ctx, input_.level_key)
        if level.status != "active":
            raise _conflict("membership.level_inactive", f"level {level.key} is {level.status}")

        async with ctx.uow_factory() as uow:
            subscription = await _find_subscription(uow, input_.subject_type, input_.subject_id)
            if subscription is not None:
                replay = await _find_cycle_by_key(uow, subscription.id, input_.idempotency_key)
                if replay is not None:
                    _validate_prepare_replay(replay, input_)
                    return _to_cycle(replay, subscription)
                if (
                    input_.expected_version is not None
                    and subscription.version != input_.expected_version
                ):
                    raise _conflict(
                        "membership.subscription_version_conflict",
                        "expected version "
                        f"{input_.expected_version}, current version is {subscription.version}",
                    )
                if subscription.status in {"pending_activation", "active", "cancelled"}:
                    raise _conflict(
                        "membership.cycle_overlap",
                        f"subscription {subscription.id} already has a current cycle",
                    )
                if not level.renewal_allowed:
                    raise _conflict(
                        "membership.renewal_not_allowed",
                        f"level {level.key} does not allow renewal",
                    )

            now = ctx.clock.utc_now()
            cycle_end = now + timedelta(days=level.cycle_days)
            if subscription is None:
                if input_.expected_version is not None:
                    raise _conflict(
                        "membership.subscription_version_conflict",
                        "cannot supply an expected version for a new subscription",
                    )
                subscription = MembershipSubscription(
                    subject_type=input_.subject_type,
                    subject_id=input_.subject_id,
                    level_key=level.key,
                    cycle_start=now,
                    cycle_end=cycle_end,
                    status="pending_activation",
                    auto_renew=input_.auto_renew,
                    granted_points=level.cycle_points_amount,
                    renewal_count=0,
                    source_type=input_.source_type,
                    source_ref=input_.source_ref,
                )
                uow.session.add(subscription)
                await uow.session.flush()
            else:
                subscription.level_key = level.key
                subscription.cycle_start = now
                subscription.cycle_end = cycle_end
                subscription.status = "pending_activation"
                subscription.auto_renew = input_.auto_renew
                subscription.granted_points = level.cycle_points_amount
                subscription.source_type = input_.source_type
                subscription.source_ref = input_.source_ref
                subscription.cancelled_at = None
                subscription.expired_at = None
                subscription.terminated_at = None
                subscription.renewal_count += 1
                subscription.version += 1

            cycle = MembershipCycle(
                subscription_id=subscription.id,
                level_key=level.key,
                cycle_start=now,
                cycle_end=cycle_end,
                cycle_points_amount=level.cycle_points_amount,
                state="prepared",
                source_type=input_.source_type,
                source_ref=input_.source_ref,
                idempotency_key=input_.idempotency_key,
            )
            uow.session.add(cycle)
            await uow.session.flush()
            subscription.cycle_id = cycle.id
            await _emit(
                ctx, uow, key="membership.cycle_prepared.v1", subscription=subscription, cycle=cycle
            )
            await uow.commit()
            return _to_cycle(cycle, subscription)
        raise AssertionError("unreachable: prepare subscription cycle completed")


class AttachPointsGrant:
    """Bind one opaque points entry and atomically activate its prepared cycle."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: AttachPointsGrantInput) -> MembershipCycleDTO:
        ctx = self._ctx
        try:
            points_entry_ref = str(uuid.UUID(input_.points_entry_ref))
        except ValueError as exc:
            raise _validation(
                "membership.invalid_points_entry_ref", "points entry ref must be a UUID"
            ) from exc

        async with ctx.uow_factory() as uow:
            cycle = await _get_cycle(uow, input_.cycle_id)
            subscription = await _get_subscription(uow, cycle.subscription_id)
            if cycle.state == "activated":
                if cycle.points_entry_ref != points_entry_ref:
                    raise _conflict(
                        "membership.points_grant_already_attached",
                        "cycle cannot be rebound to another points entry",
                    )
                return _to_cycle(cycle, subscription)
            if cycle.state != "prepared":
                raise _conflict(
                    "membership.cycle_not_prepared", f"cycle {cycle.id} is {cycle.state}"
                )
            if subscription.cycle_id != cycle.id or subscription.status != "pending_activation":
                raise _conflict(
                    "membership.subscription_cycle_mismatch",
                    "prepared cycle is not the subscription's current cycle",
                )

            cycle.points_entry_ref = points_entry_ref
            cycle.attach_idempotency_key = input_.idempotency_key
            cycle.state = "activated"
            cycle.version += 1
            subscription.status = "active"
            subscription.version += 1
            event_key = (
                "membership.renewed.v1"
                if subscription.renewal_count > 0
                else "membership.activated.v1"
            )
            await _emit(ctx, uow, key=event_key, subscription=subscription, cycle=cycle)
            await uow.commit()
            return _to_cycle(cycle, subscription)
        raise AssertionError("unreachable: attach points grant completed")


class MarkCycleFailed:
    """Record permanent failure for a cycle that has not been activated."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: MarkCycleFailedInput) -> MembershipCycleDTO:
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            cycle = await _get_cycle(uow, input_.cycle_id)
            subscription = await _get_subscription(uow, cycle.subscription_id)
            if cycle.state == "failed":
                if cycle.failure_code != input_.failure_code:
                    raise _conflict(
                        "membership.cycle_failure_already_recorded",
                        "cycle failure reason cannot be changed",
                    )
                return _to_cycle(cycle, subscription)
            if cycle.state != "prepared":
                raise _conflict(
                    "membership.cycle_not_prepared", f"cycle {cycle.id} is {cycle.state}"
                )
            cycle.state = "failed"
            cycle.failure_code = input_.failure_code
            cycle.version += 1
            if subscription.cycle_id == cycle.id:
                subscription.status = "failed"
                subscription.version += 1
            await _emit(
                ctx, uow, key="membership.cycle_failed.v1", subscription=subscription, cycle=cycle
            )
            await uow.commit()
            return _to_cycle(cycle, subscription)
        raise AssertionError("unreachable: mark cycle failed completed")


class CancelSubscription:
    """Stop renewal while preserving entitlement through the current cycle end."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: CancelInput) -> SubscriptionDTO:
        ctx = self._ctx
        async with ctx.uow_factory() as uow:
            subscription = await _get_subscription(uow, input_.subscription_id)
            if subscription.status == "cancelled":
                return _to_subscription(subscription)
            if subscription.status != "active":
                raise _conflict(
                    "membership.not_active",
                    f"subscription {subscription.id} is {subscription.status}",
                )
            subscription.status = "cancelled"
            subscription.auto_renew = False
            subscription.cancelled_at = ctx.clock.utc_now()
            subscription.version += 1
            await _emit(ctx, uow, key="membership.cancelled.v1", subscription=subscription)
            await uow.commit()
            return _to_subscription(subscription)
        raise AssertionError("unreachable: cancel subscription completed")


class TerminateSubscription:
    """Terminate current membership entitlement without touching points."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self, input_: TerminateInput) -> SubscriptionDTO:
        ctx = self._ctx
        if PERMISSION_MANAGE not in ctx.permissions and "membership.manage" not in ctx.permissions:
            raise _error(
                "membership.forbidden",
                ErrorCategory.FORBIDDEN,
                f"requires permission {PERMISSION_MANAGE}",
            )
        async with ctx.uow_factory() as uow:
            subscription = await _get_subscription(uow, input_.subscription_id)
            if subscription.status == "terminated":
                return _to_subscription(subscription)
            if subscription.status not in {"active", "cancelled"}:
                raise _conflict(
                    "membership.not_active",
                    f"subscription {subscription.id} is {subscription.status}",
                )
            subscription.status = "terminated"
            subscription.auto_renew = False
            subscription.terminated_at = ctx.clock.utc_now()
            subscription.version += 1
            await _emit(ctx, uow, key="membership.terminated.v1", subscription=subscription)
            await uow.commit()
            return _to_subscription(subscription)
        raise AssertionError("unreachable: terminate subscription completed")


class ExpireSubscription:
    """Converge ended active or cancelled subscriptions without touching points."""

    def __init__(self, ctx: CommandContext) -> None:
        self._ctx = ctx

    async def __call__(self) -> list[SubscriptionDTO]:
        ctx = self._ctx
        expired: list[SubscriptionDTO] = []
        async with ctx.uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(MembershipSubscription).where(
                            MembershipSubscription.status.in_(("active", "cancelled")),
                            MembershipSubscription.cycle_end <= ctx.clock.utc_now(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for subscription in rows:
                subscription.status = "expired"
                subscription.expired_at = ctx.clock.utc_now()
                subscription.version += 1
                await _emit(ctx, uow, key="membership.expired.v1", subscription=subscription)
                expired.append(_to_subscription(subscription))
            await uow.commit()
        return expired


def _validate_prepare_replay(cycle: MembershipCycle, input_: PrepareSubscriptionCycleInput) -> None:
    if (
        cycle.level_key != input_.level_key
        or cycle.source_type != input_.source_type
        or cycle.source_ref != input_.source_ref
    ):
        raise _conflict(
            "membership.idempotency_conflict", "idempotency key was used with different cycle input"
        )


async def _find_subscription(
    uow: UnitOfWork, subject_type: str, subject_id: str
) -> MembershipSubscription | None:
    return cast(
        MembershipSubscription | None,
        (
            await uow.session.execute(
                select(MembershipSubscription).where(
                    MembershipSubscription.subject_type == subject_type,
                    MembershipSubscription.subject_id == subject_id,
                )
            )
        )
        .scalars()
        .first(),
    )


async def _find_cycle_by_key(
    uow: UnitOfWork, subscription_id: uuid.UUID, idempotency_key: str
) -> MembershipCycle | None:
    return cast(
        MembershipCycle | None,
        (
            await uow.session.execute(
                select(MembershipCycle).where(
                    MembershipCycle.subscription_id == subscription_id,
                    MembershipCycle.idempotency_key == idempotency_key,
                )
            )
        )
        .scalars()
        .first(),
    )


async def _get_subscription(uow: UnitOfWork, subscription_id: Any) -> MembershipSubscription:
    try:
        identifier = uuid.UUID(str(subscription_id))
    except ValueError as exc:
        raise _not_found(
            "membership.subscription_not_found", f"subscription {subscription_id}"
        ) from exc
    row = await uow.session.get(MembershipSubscription, identifier)
    if row is None:
        raise _not_found("membership.subscription_not_found", f"subscription {subscription_id}")
    return cast(MembershipSubscription, row)


async def _get_cycle(uow: UnitOfWork, cycle_id: Any) -> MembershipCycle:
    try:
        identifier = uuid.UUID(str(cycle_id))
    except ValueError as exc:
        raise _not_found("membership.cycle_not_found", f"cycle {cycle_id}") from exc
    row = await uow.session.get(MembershipCycle, identifier)
    if row is None:
        raise _not_found("membership.cycle_not_found", f"cycle {cycle_id}")
    return cast(MembershipCycle, row)


def _to_subscription(row: MembershipSubscription) -> SubscriptionDTO:
    return SubscriptionDTO(
        id=str(row.id),
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        level_key=row.level_key,
        cycle_start=_utc(row.cycle_start),
        cycle_end=_utc(row.cycle_end),
        status=row.status,
        auto_renew=row.auto_renew,
        granted_points=row.granted_points,
        renewal_count=row.renewal_count,
        cycle_id=str(row.cycle_id) if row.cycle_id else None,
        cycle_points_amount=row.granted_points,
        source_type=row.source_type,
        source_ref=row.source_ref,
        cancelled_at=_utc(row.cancelled_at) if row.cancelled_at else None,
        expired_at=_utc(row.expired_at) if row.expired_at else None,
        terminated_at=_utc(row.terminated_at) if row.terminated_at else None,
        version=row.version,
    )


def _to_cycle(row: MembershipCycle, subscription: MembershipSubscription) -> MembershipCycleDTO:
    return MembershipCycleDTO(
        cycle_id=str(row.id),
        subscription_id=str(row.subscription_id),
        subject_type=subscription.subject_type,
        subject_id=subscription.subject_id,
        level_key=row.level_key,
        cycle_start=_utc(row.cycle_start),
        cycle_end=_utc(row.cycle_end),
        cycle_points_amount=row.cycle_points_amount,
        state=row.state,
        source_type=row.source_type,
        source_ref=row.source_ref,
        points_entry_ref=row.points_entry_ref,
        idempotency_key=row.idempotency_key,
        failure_code=row.failure_code,
        version=row.version,
    )
