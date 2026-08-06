"""Taxonomy capability tests.

Contract source: context/spec/capabilities/taxonomy.md §8.

Covers dimension registry fail-fast, single/multiple selection rules,
target type validation, OR-within / AND-across queries, report-only orphan
diagnostics and the absence of content imports.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY
from inc.capabilities.taxonomy.commands import (
    ArchiveTerm,
    AssignTerms,
    CommandContext,
    CreateTerm,
    RemoveTargetAssignments,
    SyncDimensionDefinitions,
    UpdateTerm,
)
from inc.capabilities.taxonomy.diagnostics import TaxonomyDiagnostics
from inc.capabilities.taxonomy.dimensions import DimensionRegistry, DimensionSpec
from inc.capabilities.taxonomy.events import TAXONOMY_EVENT_SCHEMAS
from inc.capabilities.taxonomy.models import TaxonomyAssignment
from inc.capabilities.taxonomy.ports import TargetExistsPort
from inc.capabilities.taxonomy.queries import TaxonomyQueries
from inc.capabilities.taxonomy.schemas import AssignTermsInput, CreateTermInput, UpdateTermInput
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxMessage, OutboxWriter


def make_category() -> DimensionSpec:
    return DimensionSpec(
        dimension_key="category",
        version="1",
        display_name="Category",
        target_types=("post",),
        selection_mode="single",
        min_items=0,
        max_items=1,
        manage_permission="taxonomy.manage",
    )


def make_tag() -> DimensionSpec:
    return DimensionSpec(
        dimension_key="tag",
        version="1",
        display_name="Tag",
        target_types=("post",),
        selection_mode="multiple",
        min_items=0,
        max_items=10,
        manage_permission="taxonomy.manage",
    )


@pytest.fixture
def dimensions() -> DimensionRegistry:
    registry = DimensionRegistry()
    registry.register(make_category())
    registry.register(make_tag())
    return registry


class FakeTargets:
    def __init__(self, existing: set[str]) -> None:
        self._existing = existing

    async def __call__(self, target_type: str, target_id: str) -> bool:
        return f"{target_type}:{target_id}" in self._existing


class FakeBatchTargets:
    def __init__(self, existing: set[str]) -> None:
        self._existing = existing

    async def __call__(self, target_type: str, target_ids: list[str]) -> dict[str, bool]:
        return {
            target_id: f"{target_type}:{target_id}" in self._existing for target_id in target_ids
        }


@pytest.fixture
def target_exists() -> TargetExistsPort:
    return FakeTargets({"post:11111111-1111-1111-1111-111111111111"})


@pytest.fixture
def ctx(
    uow_factory: UoWFactory,
    clock: Any,
    dimensions: DimensionRegistry,
    target_exists: TargetExistsPort,
    schema_registry: EventSchemaRegistry,
) -> CommandContext:
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        dimensions=dimensions,
        target_exists=target_exists,
        permissions=frozenset({"taxonomy.manage"}),
        actor_id="tax-admin",
        trace_id="trace-1",
    )


@pytest.fixture
def schema_registry() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    for key, schema in TAXONOMY_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded

    registry.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    return registry


@pytest.fixture
def queries(uow_factory: UoWFactory, dimensions: DimensionRegistry) -> TaxonomyQueries:
    return TaxonomyQueries(uow_factory=uow_factory, dimensions=dimensions)


TARGET = "post:11111111-1111-1111-1111-111111111111"


async def create_term(ctx: CommandContext, dimension: str, name: str, slug: str | None = None):
    return await CreateTerm(ctx)(
        dimension,
        CreateTermInput(
            name=name,
            slug=slug or name.lower().replace(" ", "-") or f"term-{uuid.uuid4().hex[:6]}",
        ),
    )


# --- registry ------------------------------------------------------------


def test_dimension_registry_rejects_duplicates(dimensions: DimensionRegistry) -> None:
    with pytest.raises(KernelError) as excinfo:
        dimensions.register(make_category())
    assert excinfo.value.code == "taxonomy.duplicate_dimension"


def test_dimension_spec_validation() -> None:
    with pytest.raises(ValueError, match="selection_mode"):
        DimensionSpec(
            dimension_key="bad",
            version="1",
            display_name="B",
            target_types=("post",),
            selection_mode="both",
        )
    with pytest.raises(ValueError, match="invalid min/max"):
        DimensionSpec(
            dimension_key="bad", version="1", display_name="B", target_types=("post",), max_items=0
        )
    with pytest.raises(ValueError, match="single mode"):
        DimensionSpec(
            dimension_key="bad",
            version="1",
            display_name="B",
            target_types=("post",),
            selection_mode="single",
            max_items=5,
        )


# --- terms ---------------------------------------------------------------


async def test_create_and_update_term(ctx: CommandContext) -> None:
    term = await create_term(ctx, "tag", "Tech")
    assert term.dimension_key == "tag" and term.status == "active"
    with pytest.raises(KernelError) as excinfo:
        await create_term(ctx, "tag", "Tech2", slug=term.slug)
    assert excinfo.value.code == "taxonomy.duplicate_slug"
    updated = await UpdateTerm(ctx)(uuid.UUID(term.id), UpdateTermInput(name="Technology"))
    assert updated.name == "Technology"
    archived = await ArchiveTerm(ctx)(uuid.UUID(term.id))
    assert archived.status == "archived"


async def test_create_term_unknown_dimension(ctx: CommandContext) -> None:
    with pytest.raises(KernelError) as excinfo:
        await create_term(ctx, "ghost", "X")
    assert excinfo.value.code == "taxonomy.unknown_dimension"


async def test_term_requires_manage_permission(
    uow_factory: UoWFactory,
    clock: Any,
    dimensions: DimensionRegistry,
    target_exists: TargetExistsPort,
    schema_registry: EventSchemaRegistry,
) -> None:
    restricted = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        dimensions=dimensions,
        target_exists=target_exists,
        permissions=frozenset({"taxonomy.read"}),
    )
    with pytest.raises(KernelError) as excinfo:
        await create_term(restricted, "tag", "No")
    assert excinfo.value.code == "taxonomy.forbidden"


async def test_remove_target_assignments_requires_manage_permission(
    ctx: CommandContext,
    uow_factory: UoWFactory,
    clock: Any,
    dimensions: DimensionRegistry,
    target_exists: TargetExistsPort,
    schema_registry: EventSchemaRegistry,
) -> None:
    restricted = CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(schema_registry, clock),
        dimensions=dimensions,
        target_exists=target_exists,
        permissions=frozenset({"taxonomy.read"}),
    )
    with pytest.raises(KernelError) as excinfo:
        await RemoveTargetAssignments(restricted)("post", TARGET.split(":")[1])
    assert excinfo.value.code == "taxonomy.forbidden"
    with pytest.raises(KernelError) as excinfo:
        await RemoveTargetAssignments(ctx)("post", "not-a-uuid")
    assert excinfo.value.code == "taxonomy.invalid_uuid"


async def test_unknown_dimension_is_validation_error(ctx: CommandContext) -> None:
    with pytest.raises(KernelError) as excinfo:
        await create_term(ctx, "ghost", "X")
    assert excinfo.value.code == "taxonomy.unknown_dimension"
    assert excinfo.value.category.value == "validation"


async def test_assign_terms_unknown_dimension_is_validation_error(ctx: CommandContext) -> None:
    tag = await create_term(ctx, "tag", "G")
    with pytest.raises(KernelError) as excinfo:
        await AssignTerms(ctx)(
            "ghost",
            AssignTermsInput(
                target_type="post",
                target_id=uuid.UUID(TARGET.split(":")[1]),
                term_ids=[uuid.UUID(tag.id)],
            ),
        )
    assert excinfo.value.category.value == "validation"


async def test_update_archived_term_single_commit_events(
    ctx: CommandContext, uow_factory: UoWFactory
) -> None:
    term = await create_term(ctx, "tag", "Single")
    async with uow_factory() as uow:
        before = (await uow.session.execute(select(OutboxMessage))).scalars().all()
    term_id = uuid.UUID(term.id)
    await UpdateTerm(ctx)(term_id, UpdateTermInput(name="Single2"))
    await ArchiveTerm(ctx)(term_id)
    async with uow_factory() as uow:
        after = (await uow.session.execute(select(OutboxMessage))).scalars().all()
    keys = [row.envelope.event_key for row in after[len(before) :]]
    assert keys.count("taxonomy.term_updated.v1") == 1
    assert keys.count("taxonomy.term_archived.v1") == 1
    assert keys.count(AUDIT_EVENT_KEY) == 2

    # idempotent archive: already archived -> no event
    await ArchiveTerm(ctx)(term_id)
    async with uow_factory() as uow:
        final = (await uow.session.execute(select(OutboxMessage))).scalars().all()
    assert len(final) == len(after)

    # empty update rejected
    with pytest.raises(KernelError) as excinfo:
        await UpdateTerm(ctx)(term_id, UpdateTermInput())
    assert excinfo.value.code == "taxonomy.empty_update"


# --- assignments ---------------------------------------------------------


async def test_assign_terms_single_mode_rules(ctx: CommandContext) -> None:
    category_a = await create_term(ctx, "category", "News")
    category_b = await create_term(ctx, "category", "Sports")
    target = uuid.UUID(TARGET.split(":")[1])
    await AssignTerms(
        ctx,
    )(
        "category",
        AssignTermsInput(target_type="post", target_id=target, term_ids=[uuid.UUID(category_a.id)]),
    )
    with pytest.raises(KernelError) as excinfo:
        await AssignTerms(ctx)(
            "category",
            AssignTermsInput(
                target_type="post",
                target_id=target,
                term_ids=[uuid.UUID(category_a.id), uuid.UUID(category_b.id)],
            ),
        )
    assert excinfo.value.code == "taxonomy.too_many_terms"


async def test_assign_terms_multiple_mode_and_replacement(
    ctx: CommandContext, queries: TaxonomyQueries
) -> None:
    tag_a = await create_term(ctx, "tag", "A")
    tag_b = await create_term(ctx, "tag", "B")
    target = uuid.UUID(TARGET.split(":")[1])
    await AssignTerms(
        ctx,
    )(
        "tag",
        AssignTermsInput(target_type="post", target_id=target, term_ids=[uuid.UUID(tag_a.id)]),
    )
    await AssignTerms(
        ctx,
    )(
        "tag",
        AssignTermsInput(
            target_type="post",
            target_id=target,
            term_ids=[uuid.UUID(tag_a.id), uuid.UUID(tag_b.id)],
        ),
    )
    assigned = await queries.get_target_terms("post", target)
    assert {t.slug for t in assigned["tag"]} == {"a", "b"}
    await AssignTerms(
        ctx,
    )(
        "tag",
        AssignTermsInput(target_type="post", target_id=target, term_ids=[uuid.UUID(tag_b.id)]),
    )
    assigned = await queries.get_target_terms("post", target)
    assert [t.slug for t in assigned["tag"]] == ["b"]


async def test_assign_validates_target_and_term_state(ctx: CommandContext) -> None:
    ghost = uuid.uuid4()
    tag = await create_term(ctx, "tag", "G")
    with pytest.raises(KernelError) as excinfo:
        await AssignTerms(ctx)(
            "tag",
            AssignTermsInput(target_type="post", target_id=ghost, term_ids=[uuid.UUID(tag.id)]),
        )
    assert excinfo.value.code == "taxonomy.target_missing"

    archived = await create_term(ctx, "tag", "Dead")
    await ArchiveTerm(ctx)(uuid.UUID(archived.id))
    with pytest.raises(KernelError) as excinfo:
        await AssignTerms(ctx)(
            "tag",
            AssignTermsInput(
                target_type="post",
                target_id=uuid.UUID(TARGET.split(":")[1]),
                term_ids=[uuid.UUID(archived.id)],
            ),
        )
    assert excinfo.value.code == "taxonomy.term_inactive"

    with pytest.raises(KernelError) as excinfo:
        await AssignTerms(ctx)(
            "tag",
            AssignTermsInput(
                target_type="page",
                target_id=uuid.UUID(TARGET.split(":")[1]),
                term_ids=[uuid.UUID(tag.id)],
            ),
        )
    assert excinfo.value.code == "taxonomy.target_type_not_allowed"


async def test_remove_target_assignments(ctx: CommandContext, uow_factory: UoWFactory) -> None:
    tag = await create_term(ctx, "tag", "R")
    target = uuid.UUID(TARGET.split(":")[1])
    await AssignTerms(
        ctx,
    )(
        "tag",
        AssignTermsInput(target_type="post", target_id=target, term_ids=[uuid.UUID(tag.id)]),
    )
    await RemoveTargetAssignments(ctx)("post", TARGET.split(":")[1])
    await RemoveTargetAssignments(ctx)("post", TARGET.split(":")[1])  # idempotent
    async with uow_factory() as uow:
        count = (await uow.session.execute(select(TaxonomyAssignment.id))).scalars().all()
    assert count == []


# --- queries -------------------------------------------------------------


async def test_find_targets_or_within_and_across(
    ctx: CommandContext, queries: TaxonomyQueries, uow_factory: UoWFactory
) -> None:
    existing = {
        "post:11111111-1111-1111-1111-111111111111",
        "post:22222222-2222-2222-2222-222222222222",
        "post:33333333-3333-3333-3333-333333333333",
    }
    special = FakeTargets(existing)
    ctx2 = CommandContext(
        uow_factory=uow_factory,
        clock=ctx.clock,
        outbox=ctx.outbox,
        dimensions=ctx.dimensions,
        target_exists=special,
        permissions=frozenset({"taxonomy.manage"}),
    )
    tag_a = await create_term(ctx2, "tag", "Py")
    tag_b = await create_term(ctx2, "tag", "Web")
    cat = await create_term(ctx2, "category", "Tut")
    ids = {
        "post:11111111-1111-1111-1111-111111111111": (tag_a, cat),
        "post:22222222-2222-2222-2222-222222222222": (tag_b, cat),
        "post:33333333-3333-3333-3333-333333333333": (tag_a,),
    }
    for key, (tag, *rest) in ids.items():
        target = uuid.UUID(key.split(":")[1])
        await AssignTerms(
            ctx2,
        )(
            "tag",
            AssignTermsInput(target_type="post", target_id=target, term_ids=[uuid.UUID(tag.id)]),
        )
        if rest:
            await AssignTerms(
                ctx2,
            )(
                "category",
                AssignTermsInput(
                    target_type="post",
                    target_id=target,
                    term_ids=[uuid.UUID(rest[0].id)],
                ),
            )

    or_hit = await queries.find_targets_by_terms({"tag": [str(tag_a.id), str(tag_b.id)]})
    assert set(or_hit) == {
        "post:11111111-1111-1111-1111-111111111111",
        "post:22222222-2222-2222-2222-222222222222",
        "post:33333333-3333-3333-3333-333333333333",
    }
    and_hit = await queries.find_targets_by_terms(
        {"tag": [str(tag_a.id)], "category": [str(cat.id)]}
    )
    assert and_hit == ["post:11111111-1111-1111-1111-111111111111"]


# --- sync & diagnostics --------------------------------------------------


async def test_sync_dimension_definitions_dry_run_then_apply(
    ctx: CommandContext, queries: TaxonomyQueries, uow_factory: UoWFactory
) -> None:
    report = await SyncDimensionDefinitions(ctx)(dry_run=True)
    assert report["dry_run"] is True and set(report["changes"]) == {"category", "tag"}
    report = await SyncDimensionDefinitions(ctx)(dry_run=False)
    assert set(report["changes"]) == {"category", "tag"}
    assert {d.dimension_key for d in await queries.list_dimensions()} == {"category", "tag"}
    report = await SyncDimensionDefinitions(ctx)(dry_run=True)
    assert report["changes"] == {}


async def test_orphan_diagnostics_report_only(ctx: CommandContext, uow_factory: UoWFactory) -> None:
    tag = await create_term(ctx, "tag", "Orphan")
    target = uuid.UUID(TARGET.split(":")[1])
    await AssignTerms(
        ctx,
    )(
        "tag",
        AssignTermsInput(target_type="post", target_id=target, term_ids=[uuid.UUID(tag.id)]),
    )
    diagnostics = TaxonomyDiagnostics(
        uow_factory=uow_factory,
        batch_target_exists=FakeBatchTargets(set()),
    )
    results = await diagnostics.run()
    assert results[0].code == "taxonomy.orphan_assignments"
    assert results[0].status.value == "degraded"
    async with uow_factory() as uow:
        rows = (await uow.session.execute(select(TaxonomyAssignment.id))).scalars().all()
    assert len(rows) == 1  # reported, never repaired

    diagnostics_ok = TaxonomyDiagnostics(
        uow_factory=uow_factory,
        batch_target_exists=FakeBatchTargets({TARGET}),
    )
    results = await diagnostics_ok.run()
    assert results[0].status.value == "ok"
