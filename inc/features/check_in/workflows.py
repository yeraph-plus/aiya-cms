"""Check-in workflow: explicit daily reward credit.

Contract source: context/spec/features.md §4.3.

The workflow idempotency key is subject + program + business date, so
concurrent check-ins produce exactly one reward. The activity computes the
business date once and the runner persists the step result, so replays
never re-read the clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from inc.capabilities.points.commands import CommandContext as PointsCommandContext
from inc.capabilities.points.commands import CreditPoints
from inc.capabilities.points.schemas import CreditDebitInput
from inc.kernel.db import UnitOfWork
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time import Clock
from inc.kernel.workflow import ActivitySpec, WorkflowSpec

CHECK_IN_WORKFLOW_KEY = "checkin.reward.v1"
REWARD_BEHAVIOR = "daily_check_in.reward"


def business_date_for(clock: Clock, timezone: str) -> str:
    """Local business date fixed at the explicit user action (spec §4.3)."""

    return clock.utc_now().astimezone(ZoneInfo(timezone)).date().isoformat()


@dataclass(frozen=True, slots=True)
class CheckInContext:
    points_ctx: PointsCommandContext
    clock: Clock


def check_in_idempotency_key(*, subject_id: str, program_key: str, business_date: str) -> str:
    return f"{REWARD_BEHAVIOR}:{subject_id}:{program_key}:{business_date}"


def build_check_in_workflow_spec(*, ctx: CheckInContext) -> WorkflowSpec:
    async def reward_step(
        uow: UnitOfWork, data: dict[str, Any], activity_ctx: Any
    ) -> dict[str, Any]:
        workflow = data.get("workflow", {})
        subject_type = workflow["subject_type"]
        subject_id = workflow["subject_id"]
        source_id = workflow["source_id"]
        program_key = workflow["program_key"]
        business_date = workflow.get("business_date")
        if business_date is None:
            raise KernelError(
                code="checkin.missing_business_date",
                category=ErrorCategory.INTERNAL,
                message="business date must be fixed at workflow start",
            )
        entry = await CreditPoints(ctx.points_ctx)(
            REWARD_BEHAVIOR,
            CreditDebitInput(
                subject_type=subject_type,
                subject_id=subject_id,
                amount=ctx.points_ctx.behaviors.require(REWARD_BEHAVIOR).fixed_amount or 10,
                source_type="system",
                source_id=source_id,
                idempotency_key=check_in_idempotency_key(
                    subject_id=subject_id, program_key=program_key, business_date=business_date
                ),
                actor_type="user",
                actor_id=subject_id,
            ),
        )
        return {"entry_id": entry.id, "business_date": business_date}

    return WorkflowSpec(
        key=CHECK_IN_WORKFLOW_KEY,
        version="1",
        activities=(
            ActivitySpec(
                key="checkin.reward.step.v1",
                timeout_seconds=30.0,
                handler=reward_step,
            ),
        ),
    )
