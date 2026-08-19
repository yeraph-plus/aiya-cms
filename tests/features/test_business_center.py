from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from inc.features.business_center import (
    ARCHIVE_PART_BYTES,
    ArchiveFileCost,
    ArchiveManifestCostBasis,
    BusinessPrincipal,
    BusinessProductRegistry,
    ConsumeBusinessProduct,
    ConsumptionRecord,
    FulfillmentTemporarilyUnavailable,
    QuoteBusinessProduct,
    QuoteRequest,
    QuoteTokenCodec,
    archive_product_spec,
    price_archive_files_fixed_v1,
)
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.security.signing import HmacSigner


@dataclass
class FakeClock:
    now: datetime = datetime(2026, 8, 19, tzinfo=UTC)

    def utc_now(self) -> datetime:
        return self.now


@dataclass
class CostBasis:
    basis: ArchiveManifestCostBasis

    async def resolve(self, **_: Any) -> ArchiveManifestCostBasis:
        return self.basis


@dataclass
class RecordingPoints:
    balance: int = 10_000
    calls: list[Any] = field(default_factory=list)
    entries: dict[str, str] = field(default_factory=dict)

    async def debit(self, request: Any) -> str:
        if request.idempotency_key in self.entries:
            return self.entries[request.idempotency_key]
        if self.balance < request.amount:
            raise KernelError(
                code="points.insufficient_balance",
                category=ErrorCategory.CONFLICT,
                message="insufficient",
            )
        self.balance -= request.amount
        self.calls.append(request)
        ref = f"entry-{len(self.calls)}"
        self.entries[request.idempotency_key] = ref
        return ref


@dataclass
class RecordingFulfillment:
    fail_once: bool = False
    calls: list[Any] = field(default_factory=list)
    results: dict[str, str] = field(default_factory=dict)

    async def fulfill(self, request: Any) -> str:
        if request.idempotency_key in self.results:
            return self.results[request.idempotency_key]
        self.calls.append(request)
        if self.fail_once:
            self.fail_once = False
            raise FulfillmentTemporarilyUnavailable
        ref = f"grant-{len(self.results) + 1}"
        self.results[request.idempotency_key] = ref
        return ref


@dataclass
class MemoryState:
    records: dict[str, ConsumptionRecord] = field(default_factory=dict)

    async def get_or_create(self, record: ConsumptionRecord) -> ConsumptionRecord:
        return self.records.setdefault(record.consumption_id, record)

    async def save(self, record: ConsumptionRecord) -> None:
        self.records[record.consumption_id] = record


def manifest(*, version: str = "7", last_size: int = 123) -> ArchiveManifestCostBasis:
    return ArchiveManifestCostBasis(
        target_ref="work-1",
        manifest_version=version,
        files=(
            ArchiveFileCost(
                file_id="file-1", version=3, part_number=1, size_bytes=ARCHIVE_PART_BYTES
            ),
            ArchiveFileCost(file_id="file-2", version=2, part_number=2, size_bytes=last_size),
        ),
    )


def registry() -> BusinessProductRegistry:
    result = BusinessProductRegistry(
        pricing_policy_keys=frozenset({"archive.files.fixed.v1"}),
        fulfillment_port_keys=frozenset({"archive.issue_download_grant.v1"}),
        allowed_scopes=frozenset({"business.quote", "business.consume", "archive.download"}),
    )
    result.register(archive_product_spec(client_ids=frozenset({"site"}), audience="users"))
    result.freeze()
    return result


def principal(*, subject: str = "user-1") -> BusinessPrincipal:
    return BusinessPrincipal(
        subject=subject,
        client_id="site",
        audience="users",
        scopes=frozenset({"business.quote", "business.consume", "archive.download"}),
    )


async def harness(
    *, balance: int = 10_000, fail_once: bool = False
) -> tuple[Any, Any, RecordingPoints, RecordingFulfillment, MemoryState, FakeClock, CostBasis]:
    clock = FakeClock()
    basis = CostBasis(manifest())
    tokens = QuoteTokenCodec(HmacSigner(b"test-secret"))
    products = registry()
    points = RecordingPoints(balance=balance)
    fulfillment = RecordingFulfillment(fail_once=fail_once)
    state = MemoryState()
    quote = QuoteBusinessProduct(
        products=products, cost_basis=basis, token_codec=tokens, clock=clock
    )
    consume = ConsumeBusinessProduct(
        products=products,
        cost_basis=basis,
        token_codec=tokens,
        points=points,
        fulfillments={"archive.issue_download_grant.v1": fulfillment},
        state=state,
        clock=clock,
    )
    return quote, consume, points, fulfillment, state, clock, basis


def test_registry_is_explicit_validated_and_frozen() -> None:
    products = registry()
    assert products.frozen
    assert products.require("archive.download.manifest").program_key == "credit"
    with pytest.raises(KernelError) as excinfo:
        products.register(archive_product_spec(client_ids=frozenset({"site"}), audience="users"))
    assert excinfo.value.code == "business_center.registry_frozen"


def test_archive_pricing_is_fixed_per_file_and_digest_tracks_snapshot() -> None:
    priced = price_archive_files_fixed_v1(manifest())
    changed = price_archive_files_fixed_v1(manifest(last_size=124))
    assert priced.amount == 200
    assert priced.explanation.unit_points == 100
    assert priced.fulfillment.file_ids == ("file-1", "file-2")
    assert priced.target_digest != changed.target_digest
    with pytest.raises(KernelError) as excinfo:
        price_archive_files_fixed_v1(manifest(last_size=ARCHIVE_PART_BYTES + 1))
    assert excinfo.value.code == "business_center.invalid_cost_basis"


async def test_quote_is_signed_bound_and_has_no_client_amount_or_program() -> None:
    quote_service, _, _, _, _, _, _ = await harness()
    quoted = await quote_service(
        QuoteRequest(product_key="archive.download.manifest", target_ref="work-1"),
        principal=principal(),
    )
    assert quoted.amount == 200
    assert quoted.program_key == "credit"
    with pytest.raises(ValidationError):
        QuoteRequest.model_validate(
            {
                "product_key": "archive.download.manifest",
                "target_ref": "work-1",
                "amount": 1,
            }
        )


async def test_same_idempotency_debits_and_fulfills_once_under_concurrency() -> None:
    quote_service, consume, points, fulfillment, _, _, _ = await harness()
    quoted = await quote_service(
        QuoteRequest(product_key="archive.download.manifest", target_ref="work-1"),
        principal=principal(),
    )
    first, second = await asyncio.gather(
        consume(
            quote_token=quoted.token,
            idempotency_key="request-1",
            principal=principal(),
        ),
        consume(
            quote_token=quoted.token,
            idempotency_key="request-1",
            principal=principal(),
        ),
    )
    assert first == second
    assert first.status == "fulfilled"
    assert len(points.calls) == len(fulfillment.calls) == 1
    assert points.calls[0].amount == 200
    assert points.calls[0].program_key == "credit"


async def test_pending_fulfillment_recovers_without_second_debit_after_expiry() -> None:
    quote_service, consume, points, fulfillment, _, clock, _ = await harness(fail_once=True)
    quoted = await quote_service(
        QuoteRequest(product_key="archive.download.manifest", target_ref="work-1"),
        principal=principal(),
    )
    pending = await consume(
        quote_token=quoted.token,
        idempotency_key="request-1",
        principal=principal(),
    )
    assert pending.status == "fulfillment_pending"
    clock.now += timedelta(hours=1)
    complete = await consume(
        quote_token=quoted.token,
        idempotency_key="request-1",
        principal=principal(),
    )
    assert complete.status == "fulfilled"
    assert len(points.calls) == 1
    assert len(fulfillment.calls) == 2


@pytest.mark.parametrize("change", ["expiry", "manifest"])
async def test_stale_quote_never_debits_or_fulfills(change: str) -> None:
    quote_service, consume, points, fulfillment, _, clock, basis = await harness()
    quoted = await quote_service(
        QuoteRequest(product_key="archive.download.manifest", target_ref="work-1"),
        principal=principal(),
    )
    if change == "expiry":
        clock.now += timedelta(hours=1)
    else:
        basis.basis = manifest(version="8")
    with pytest.raises(KernelError) as excinfo:
        await consume(
            quote_token=quoted.token,
            idempotency_key="request-1",
            principal=principal(),
        )
    assert excinfo.value.code == "business_center.quote_stale"
    assert points.calls == fulfillment.calls == []


async def test_insufficient_balance_has_stable_error_and_no_grant() -> None:
    quote_service, consume, points, fulfillment, _, _, _ = await harness(balance=199)
    quoted = await quote_service(
        QuoteRequest(product_key="archive.download.manifest", target_ref="work-1"),
        principal=principal(),
    )
    with pytest.raises(KernelError) as excinfo:
        await consume(
            quote_token=quoted.token,
            idempotency_key="request-1",
            principal=principal(),
        )
    assert excinfo.value.code == "business_center.insufficient_balance"
    assert points.calls == fulfillment.calls == []


async def test_tampered_or_cross_subject_quote_is_rejected() -> None:
    quote_service, consume, points, fulfillment, _, _, _ = await harness()
    quoted = await quote_service(
        QuoteRequest(product_key="archive.download.manifest", target_ref="work-1"),
        principal=principal(),
    )
    with pytest.raises(KernelError) as tampered:
        await consume(
            quote_token=quoted.token[:-1] + "x",
            idempotency_key="request-1",
            principal=principal(),
        )
    assert tampered.value.code == "business_center.invalid_quote"
    with pytest.raises(KernelError) as rebound:
        await consume(
            quote_token=quoted.token,
            idempotency_key="request-1",
            principal=principal(subject="user-2"),
        )
    assert rebound.value.code == "business_center.invalid_quote"
    assert points.calls == fulfillment.calls == []
