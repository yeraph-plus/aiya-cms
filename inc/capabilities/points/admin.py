"""Administrator read/write surface owned by the points capability."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from inc.capabilities.points.behaviors import PointBehaviorRegistry
from inc.capabilities.points.models import PointsAccount, PointsBalance, PointsProgram
from inc.kernel.db import Page, UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import EventEnvelope, OutboxWriter
from inc.kernel.time import Clock


class PointsProgramAdminDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    program_key: str
    display_name: str
    unit: str
    status: str
    allow_admin_reversal: bool
    version: int = 1


class PointsAccountAdminRecordDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    program_key: str
    subject_type: str
    subject_id: str
    state: str
    balance: int
    version: int


class PointsSummaryAdminDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_count: int
    account_count: int
    active_account_count: int
    frozen_account_count: int
    debt_account_count: int
    total_balance: int


class PointsProgramInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=200)
    unit: str = Field(default="points", min_length=1, max_length=32)
    allow_admin_reversal: bool = True


class PointsProgramPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    allow_admin_reversal: bool | None = None
    expected_version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> PointsProgramPatch:
        mutable_fields = {"display_name", "unit", "allow_admin_reversal"}
        if any(
            name in self.model_fields_set and getattr(self, name) is None for name in mutable_fields
        ):
            raise ValueError("patch fields must be omitted rather than null")
        return self


class PointsProgramStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True, slots=True)
class PointsAdminService:
    uow_factory: UoWFactory
    clock: Clock
    outbox: OutboxWriter
    behaviors: PointBehaviorRegistry

    async def list_programs(self) -> list[PointsProgramAdminDTO]:
        async with self.uow_factory() as uow:
            rows = (
                (
                    await uow.session.execute(
                        select(PointsProgram).order_by(PointsProgram.program_key)
                    )
                )
                .scalars()
                .all()
            )
        return [_program(row) for row in rows]

    async def create_program(
        self, body: PointsProgramInput, *, actor_id: str, trace_id: str | None
    ) -> PointsProgramAdminDTO:
        async with self.uow_factory() as uow:
            row = PointsProgram(**body.model_dump())
            uow.session.add(row)
            try:
                await uow.session.flush()
            except IntegrityError as exc:
                raise _error(
                    "points.program_exists", ErrorCategory.CONFLICT, "program key already exists"
                ) from exc
            await self._audit(
                uow,
                actor_id,
                trace_id,
                "points.program.created",
                str(row.id),
                {"program_key": row.program_key},
            )
            await uow.commit()
        return _program(row)

    async def update_program(
        self,
        program_key: str,
        body: PointsProgramPatch,
        *,
        actor_id: str,
        trace_id: str | None,
    ) -> PointsProgramAdminDTO:
        values = body.model_dump(exclude_unset=True, exclude={"expected_version"})
        async with self.uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(PointsProgram).where(PointsProgram.program_key == program_key)
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                raise _error(
                    "points.program_not_found", ErrorCategory.NOT_FOUND, "program not found"
                )
            if body.expected_version != row.version:
                raise _error(
                    "points.program_version_conflict",
                    ErrorCategory.CONFLICT,
                    "points program was changed by another administrator",
                )
            if "unit" in values and values["unit"] != row.unit:
                exists = (
                    await uow.session.execute(
                        select(PointsAccount.id).where(PointsAccount.program_id == row.id).limit(1)
                    )
                ).first()
                if exists:
                    raise _error(
                        "points.program_unit_immutable",
                        ErrorCategory.CONFLICT,
                        "program unit cannot change after accounts exist",
                    )
            for key, value in values.items():
                setattr(row, key, value)
            row.version += 1
            await self._audit(
                uow,
                actor_id,
                trace_id,
                "points.program.updated",
                str(row.id),
                {"program_key": row.program_key, "changed": sorted(values)},
            )
            await uow.commit()
        return _program(row)

    async def set_program_status(
        self,
        program_key: str,
        status: Literal["active", "inactive"],
        *,
        expected_version: int,
        reason: str,
        actor_id: str,
        trace_id: str | None,
        protected_program_key: str,
    ) -> PointsProgramAdminDTO:
        if program_key == protected_program_key and status != "active":
            raise _error(
                "points.credit_protected",
                ErrorCategory.CONFLICT,
                "credit program cannot be deactivated",
            )
        async with self.uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(PointsProgram).where(PointsProgram.program_key == program_key)
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                raise _error(
                    "points.program_not_found", ErrorCategory.NOT_FOUND, "program not found"
                )
            if row.version != expected_version:
                raise _error(
                    "points.program_version_conflict",
                    ErrorCategory.CONFLICT,
                    "points program was changed by another administrator",
                )
            if status == "inactive":
                if any(item.program_key == row.program_key for item in self.behaviors.specs()):
                    raise _error(
                        "points.program_behavior_active",
                        ErrorCategory.CONFLICT,
                        "program cannot be deactivated while a registered behavior uses it",
                    )
                nonzero = (
                    await uow.session.execute(
                        select(PointsBalance.id)
                        .where(
                            PointsBalance.account_id.in_(
                                select(PointsAccount.id).where(PointsAccount.program_id == row.id)
                            ),
                            PointsBalance.balance != 0,
                        )
                        .limit(1)
                    )
                ).first()
                if nonzero:
                    raise _error(
                        "points.program_nonzero_balance",
                        ErrorCategory.CONFLICT,
                        "program cannot be deactivated while balances are non-zero",
                    )
            row.status = status
            row.version += 1
            await self._audit(
                uow,
                actor_id,
                trace_id,
                f"points.program.{status}",
                str(row.id),
                {"program_key": program_key, "reason": reason},
            )
            await uow.commit()
        return _program(row)

    async def summary(self) -> PointsSummaryAdminDTO:
        async with self.uow_factory() as uow:
            program_count = int(
                (
                    await uow.session.execute(select(func.count()).select_from(PointsProgram))
                ).scalar_one()
            )
            account_count = int(
                (
                    await uow.session.execute(select(func.count()).select_from(PointsAccount))
                ).scalar_one()
            )
            active = int(
                (
                    await uow.session.execute(
                        select(func.count())
                        .select_from(PointsAccount)
                        .where(PointsAccount.state == "active")
                    )
                ).scalar_one()
            )
            frozen = int(
                (
                    await uow.session.execute(
                        select(func.count())
                        .select_from(PointsAccount)
                        .where(PointsAccount.state == "frozen")
                    )
                ).scalar_one()
            )
            debt = int(
                (
                    await uow.session.execute(
                        select(func.count())
                        .select_from(PointsAccount)
                        .where(PointsAccount.state == "debt")
                    )
                ).scalar_one()
            )
            total = int(
                (
                    await uow.session.execute(
                        select(func.coalesce(func.sum(PointsBalance.balance), 0))
                    )
                ).scalar_one()
            )
        return PointsSummaryAdminDTO(
            program_count=program_count,
            account_count=account_count,
            active_account_count=active,
            frozen_account_count=frozen,
            debt_account_count=debt,
            total_balance=total,
        )

    async def list_accounts(
        self, *, page: int, size: int, program_key: str | None, state: str | None
    ) -> Page[PointsAccountAdminRecordDTO]:
        async with self.uow_factory() as uow:
            statement = (
                select(PointsAccount, PointsProgram, PointsBalance)
                .join(PointsProgram, PointsProgram.id == PointsAccount.program_id)
                .join(PointsBalance, PointsBalance.account_id == PointsAccount.id)
            )
            if program_key:
                statement = statement.where(PointsProgram.program_key == program_key)
            if state:
                statement = statement.where(PointsAccount.state == state)
            statement = statement.order_by(PointsAccount.created_at.desc(), PointsAccount.id.desc())
            total = int(
                (
                    await uow.session.execute(
                        select(func.count()).select_from(statement.order_by(None).subquery())
                    )
                ).scalar_one()
            )
            rows = (
                await uow.session.execute(statement.offset((page - 1) * size).limit(size))
            ).all()
        return Page(
            items=[_account(account, program, balance) for account, program, balance in rows],
            total=total,
            page=page,
            size=size,
        )

    async def program_summary(self, program_key: str) -> tuple[PointsProgramAdminDTO, int]:
        async with self.uow_factory() as uow:
            program = (
                (
                    await uow.session.execute(
                        select(PointsProgram).where(PointsProgram.program_key == program_key)
                    )
                )
                .scalars()
                .first()
            )
            if program is None:
                raise _error(
                    "points.program_not_found", ErrorCategory.NOT_FOUND, "program not found"
                )
            count = int(
                (
                    await uow.session.execute(
                        select(func.count())
                        .select_from(PointsAccount)
                        .where(PointsAccount.program_id == program.id)
                    )
                ).scalar_one()
            )
        return _program(program), count

    async def account_target(self, account_id: uuid.UUID) -> tuple[str, str, str]:
        async with self.uow_factory() as uow:
            account = await uow.session.get(PointsAccount, account_id)
            if account is None:
                raise _error(
                    "points.account_not_found", ErrorCategory.NOT_FOUND, "points account not found"
                )
            program = await uow.session.get(PointsProgram, account.program_id)
            if program is None:
                raise _error(
                    "points.program_not_found", ErrorCategory.NOT_FOUND, "points program not found"
                )
            return program.program_key, account.subject_type, account.subject_id
        raise AssertionError("points account target query exited without returning")

    async def _audit(
        self,
        uow: Any,
        actor_id: str,
        trace_id: str | None,
        action: str,
        target_id: str,
        details: dict[str, Any],
    ) -> None:
        await self.outbox.append(
            uow,
            EventEnvelope(
                event_id=uuid.uuid7(),
                event_key="audit.entry.recorded.v1",
                occurred_at=self.clock.utc_now(),
                producer="points",
                aggregate_type="points",
                aggregate_id=target_id,
                trace_id=trace_id,
                payload={
                    "action": action,
                    "outcome": "success",
                    "occurred_at": self.clock.utc_now().isoformat(),
                    "actor_type": "user",
                    "actor_id": actor_id,
                    "target_type": "points_program",
                    "target_id": target_id,
                    "trace_id": trace_id,
                    "details": details,
                },
            ),
        )


def _program(row: PointsProgram) -> PointsProgramAdminDTO:
    return PointsProgramAdminDTO(
        id=str(row.id),
        program_key=row.program_key,
        display_name=row.display_name,
        unit=row.unit,
        status=row.status,
        allow_admin_reversal=row.allow_admin_reversal,
        version=row.version,
    )


def _account(
    account: PointsAccount, program: PointsProgram, balance: PointsBalance
) -> PointsAccountAdminRecordDTO:
    return PointsAccountAdminRecordDTO(
        account_id=str(account.id),
        program_key=program.program_key,
        subject_type=account.subject_type,
        subject_id=account.subject_id,
        state=account.state,
        balance=balance.balance,
        version=balance.version,
    )


def _error(code: str, category: ErrorCategory, message: str) -> KernelError:
    return KernelError(code=code, category=category, message=message)
