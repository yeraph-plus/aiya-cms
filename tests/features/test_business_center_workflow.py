from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from inc.features.business_center import (
    ARCHIVE_PART_BYTES,
    ArchiveFileCost,
    ArchiveManifestCostBasis,
    BusinessPrincipal,
    BusinessProductRegistry,
    QuoteClaims,
    QuoteTokenCodec,
    archive_product_spec,
    price_archive_files_fixed_v1,
)
from inc.features.business_center.workflows import (
    COMPENSATE_ACTIVITY_KEY,
    CONSUME_WORKFLOW_KEY,
    DEBIT_ACTIVITY_KEY,
    FULFILL_ACTIVITY_KEY,
    VALIDATE_ACTIVITY_KEY,
    BusinessCenterWorkflowContext,
    build_consume_workflow_spec,
    consumption_idempotency_key,
)
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.security.signing import HmacSigner
from inc.kernel.workflow import WorkflowRegistry, WorkflowRunner


def test_consume_workflow_has_durable_recovery_and_compensation_steps() -> None:
    context = BusinessCenterWorkflowContext(
        products=SimpleNamespace(),
        cost_basis=SimpleNamespace(),
        token_codec=SimpleNamespace(),
        points_ctx=SimpleNamespace(),
        archive_ctx=SimpleNamespace(),
        grant_ttl=timedelta(minutes=30),
        fulfillment_terminal_attempts=3,
    )
    spec = build_consume_workflow_spec(ctx=context)  # type: ignore[arg-type]

    assert spec.key == CONSUME_WORKFLOW_KEY
    assert tuple(activity.key for activity in spec.activities) == (
        VALIDATE_ACTIVITY_KEY,
        DEBIT_ACTIVITY_KEY,
        FULFILL_ACTIVITY_KEY,
        COMPENSATE_ACTIVITY_KEY,
    )
    assert spec.activity(FULFILL_ACTIVITY_KEY).retry.max_attempts == 3  # type: ignore[union-attr]


def test_consumption_key_binds_subject_quote_and_request_key() -> None:
    first = consumption_idempotency_key(
        subject="subject-1", quote_id="quote-1", request_key="request-1"
    )
    assert first == consumption_idempotency_key(
        subject="subject-1", quote_id="quote-1", request_key="request-1"
    )
    assert first != consumption_idempotency_key(
        subject="subject-2", quote_id="quote-1", request_key="request-1"
    )


@dataclass
class _Effects:
    debit_calls: list[str] = field(default_factory=list)
    grant_calls: list[str] = field(default_factory=list)
    reversals: list[str] = field(default_factory=list)
    committed_grants: dict[str, str] = field(default_factory=dict)
    crash_after_grant: bool = False
    always_unavailable: bool = False


def _workflow_harness(clock: Any) -> tuple[Any, Any, Any, Any]:
    basis = ArchiveManifestCostBasis(
        target_ref="work-1",
        manifest_version="1",
        files=(
            ArchiveFileCost(
                file_id="00000000-0000-0000-0000-000000000001",
                version=1,
                part_number=1,
                size_bytes=ARCHIVE_PART_BYTES,
            ),
            ArchiveFileCost(
                file_id="00000000-0000-0000-0000-000000000002",
                version=1,
                part_number=2,
                size_bytes=10,
            ),
        ),
    )
    products = BusinessProductRegistry(
        pricing_policy_keys=frozenset({"archive.files.fixed.v1"}),
        fulfillment_port_keys=frozenset({"archive.issue_download_grant.v1"}),
        allowed_scopes=frozenset({"business.quote", "business.consume", "archive.download"}),
    )
    product = archive_product_spec(client_ids=frozenset({"site"}), audience="users")
    products.register(product)
    products.freeze()
    principal = BusinessPrincipal(
        subject="subject-1",
        client_id="site",
        audience="users",
        scopes=frozenset({"business.quote", "business.consume", "archive.download"}),
    )
    codec = QuoteTokenCodec(HmacSigner(b"workflow-test-secret"))
    priced = price_archive_files_fixed_v1(basis)
    now = clock.utc_now()
    claims = QuoteClaims(
        quote_id="quote-1",
        product_key=product.product_key,
        product_version=product.version,
        pricing_policy_key=product.pricing_policy_key,
        compensation_policy_version=product.compensation_policy_version,
        amount=priced.amount,
        target_ref=basis.target_ref,
        target_digest=priced.target_digest,
        parameters={},
        subject=principal.subject,
        client_id=principal.client_id,
        audience=principal.audience,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        fulfillment=priced.fulfillment,
    )

    class CostBasis:
        async def resolve(self, **_: Any) -> ArchiveManifestCostBasis:
            return basis

    return products, CostBasis(), codec, (principal, claims)


async def _start_runner(
    monkeypatch: pytest.MonkeyPatch,
    uow_factory: Any,
    clock: Any,
    effects: _Effects,
    *,
    terminal_attempts: int = 3,
) -> tuple[WorkflowRunner, Any]:
    from inc.features.business_center import workflows

    products, cost_basis, codec, values = _workflow_harness(clock)
    principal, claims = values

    class Debit:
        def __init__(self, ctx: Any) -> None:
            del ctx

        async def __call__(self, behavior: str, input_: Any) -> Any:
            assert behavior == "business_center.consume.debit.v1"
            effects.debit_calls.append(input_.idempotency_key)
            return SimpleNamespace(id="entry-1")

    class Grant:
        def __init__(self, ctx: Any) -> None:
            del ctx

        async def __call__(self, input_: Any) -> Any:
            effects.grant_calls.append(input_.idempotency_key)
            if effects.always_unavailable:
                raise KernelError(
                    code="archive.provider_unavailable",
                    category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    message="temporary provider failure",
                )
            grant_id = effects.committed_grants.setdefault(input_.idempotency_key, "grant-1")
            if effects.crash_after_grant:
                effects.crash_after_grant = False
                raise RuntimeError("crash after grant commit")
            return SimpleNamespace(id=grant_id)

    class Reverse:
        def __init__(self, ctx: Any) -> None:
            del ctx

        async def __call__(self, entry_id: str, input_: Any) -> Any:
            assert entry_id == "entry-1"
            effects.reversals.append(input_.idempotency_key)
            return SimpleNamespace(id="reversal-1")

    monkeypatch.setattr(workflows, "DebitPoints", Debit)
    monkeypatch.setattr(workflows, "IssueDownloadGrant", Grant)
    monkeypatch.setattr(workflows, "ReverseLedgerEntry", Reverse)
    context = BusinessCenterWorkflowContext(
        products=products,
        cost_basis=cost_basis,
        token_codec=codec,
        points_ctx=SimpleNamespace(clock=clock),
        archive_ctx=SimpleNamespace(),
        fulfillment_terminal_attempts=terminal_attempts,
    )
    registry = WorkflowRegistry()
    registry.register(build_consume_workflow_spec(ctx=context))
    registry.freeze()
    runner = WorkflowRunner(uow_factory=uow_factory, registry=registry, clock=clock)
    key = consumption_idempotency_key(
        subject=principal.subject, quote_id=claims.quote_id, request_key="request-1"
    )
    instance = await runner.start(
        workflow_key=CONSUME_WORKFLOW_KEY,
        idempotency_key=key,
        input_data={
            "quote_token": codec.encode(claims),
            "principal": principal.model_dump(mode="json"),
            "consumption_key": key,
            "compensation_policy_version": "1",
        },
    )
    return runner, instance


async def test_crash_after_grant_commit_retries_without_second_debit_or_grant(
    monkeypatch: pytest.MonkeyPatch, uow_factory: Any, clock: Any
) -> None:
    effects = _Effects(crash_after_grant=True)
    runner, instance = await _start_runner(monkeypatch, uow_factory, clock, effects)

    assert await runner.advance(instance.id) == "pending"
    clock.advance(timedelta(seconds=2))
    assert await runner.advance(instance.id) == "completed"
    assert len(effects.debit_calls) == 1
    assert len(effects.grant_calls) == 2
    assert len(effects.committed_grants) == 1
    assert effects.reversals == []


async def test_terminal_fulfillment_failure_reverses_debit(
    monkeypatch: pytest.MonkeyPatch, uow_factory: Any, clock: Any
) -> None:
    effects = _Effects(always_unavailable=True)
    runner, instance = await _start_runner(
        monkeypatch, uow_factory, clock, effects, terminal_attempts=2
    )

    assert await runner.advance(instance.id) == "pending"
    clock.advance(timedelta(seconds=2))
    assert await runner.advance(instance.id) == "completed"
    assert len(effects.debit_calls) == 1
    assert len(effects.grant_calls) == 2
    assert len(effects.reversals) == 1
