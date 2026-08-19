"""Archive capability contracts."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from inc.capabilities.archive.activities import ResolveDownloadLinks
from inc.capabilities.archive.commands import (
    ActivateArchiveItem,
    ActivateDownloadGrant,
    CommandContext,
    ExpireDownloadGrant,
    IssueDownloadGrant,
    MarkArchiveItemUnavailable,
    RecordDeliveryAttempt,
    RegisterArchiveItem,
    RetireArchiveItem,
    RevokeDownloadGrant,
    VerifyArchiveItem,
)
from inc.capabilities.archive.events import ARCHIVE_EVENT_SCHEMAS
from inc.capabilities.archive.models import (
    ArchiveDeliveryAttempt,
    ArchiveDownloadGrant,
    ArchiveItem,
)
from inc.capabilities.archive.ports import FakeArchiveDeliveryProvider
from inc.capabilities.archive.queries import ArchiveQueries
from inc.capabilities.archive.schemas import (
    ArchiveLocatorInput,
    GrantStateInput,
    IssueDownloadGrantInput,
    RecordDeliveryAttemptInput,
    RegisterArchiveItemInput,
)
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.events import EventSchemaRegistry, OutboxMessage, OutboxWriter

ALL_PERMISSIONS = frozenset(
    {
        "archive.items.read",
        "archive.items.manage",
        "archive.items.verify",
        "archive.grants.read",
        "archive.grants.issue",
        "archive.grants.activate",
        "archive.grants.revoke",
        "archive.delivery.resolve",
    }
)


@pytest.fixture
def archive_context(uow_factory: UoWFactory, clock: Any) -> CommandContext:
    registry = EventSchemaRegistry()
    for key, schema in ARCHIVE_EVENT_SCHEMAS.items():
        registry.register(key, schema)
    return CommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=OutboxWriter(registry, clock),
        providers={"archive.fake": FakeArchiveDeliveryProvider()},
        permissions=ALL_PERMISSIONS,
        actor_id="admin-1",
        trace_id="trace-archive",
    )


async def _active_item(ctx: CommandContext, *, key: str = "part-1", part: int = 1) -> Any:
    locator = f"/archive/{key}"
    provider = ctx.providers["archive.fake"]
    assert isinstance(provider, FakeArchiveDeliveryProvider)
    provider.add_file(locator, display_name=f"{key}.zip", size_bytes=100 + part)
    item = await RegisterArchiveItem(ctx)(
        RegisterArchiveItemInput(
            item_key=key,
            provider_key="archive.fake",
            external_locator=ArchiveLocatorInput(value=locator),
            display_name=f"{key}.zip",
            size_bytes=100 + part,
            part_number=part,
        )
    )
    verified = await VerifyArchiveItem(ctx)(item.id)
    return await ActivateArchiveItem(ctx)(verified.id, expected_version=verified.version)


async def _active_grant(ctx: CommandContext, item_id: str) -> Any:
    grant = await IssueDownloadGrant(ctx)(
        IssueDownloadGrantInput(
            subject_type="identity",
            subject_id="user-1",
            product_ref="product-1",
            quote_ref="quote-1",
            points_entry_ref="points-entry-1",
            target_type="work",
            target_id="work-1",
            item_ids=(item_id,),
            manifest_version="work.v1",
            expires_at=ctx.clock.utc_now() + timedelta(hours=1),
            idempotency_key="consumption-1",
        )
    )
    return await ActivateDownloadGrant(ctx)(grant.id, expected_version=grant.version)


async def test_item_state_machine_and_public_dto_are_redacted(
    archive_context: CommandContext, uow_factory: UoWFactory
) -> None:
    item = await _active_item(archive_context)
    assert item.state == "active"
    public = await ArchiveQueries(ctx=archive_context).get_item_public(
        uuid.UUID(item.id), permissions=frozenset({"archive.items.read"})
    )
    assert public is not None
    dumped = public.model_dump()
    assert "provider_key" not in dumped
    assert "external_locator" not in dumped
    assert "token" not in str(dumped).lower()

    async with uow_factory() as uow:
        row = await uow.session.get(ArchiveItem, uuid.UUID(item.id))
        assert row is not None
        assert row.external_locator.value == "/archive/part-1"

    unavailable = await MarkArchiveItemUnavailable(archive_context)(
        item.id, expected_version=item.version, reason="maintenance"
    )
    assert unavailable.state == "unavailable"
    retired = await RetireArchiveItem(archive_context)(
        unavailable.id, expected_version=unavailable.version
    )
    assert retired.state == "retired"
    with pytest.raises(KernelError) as excinfo:
        await ActivateArchiveItem(archive_context)(retired.id, expected_version=retired.version)
    assert excinfo.value.code == "archive.item_retired"


async def test_grant_is_idempotent_has_subject_guard_and_rejects_snapshot_drift(
    archive_context: CommandContext, uow_factory: UoWFactory
) -> None:
    item = await _active_item(archive_context)
    grant = await _active_grant(archive_context, item.id)
    replay = await _active_grant(archive_context, item.id)
    assert replay.id == grant.id
    assert replay.manifest_digest

    queries = ArchiveQueries(ctx=archive_context)
    own = await queries.get_grant_for_subject(
        grant.id, subject_type="identity", subject_id="user-1"
    )
    assert own is not None
    with pytest.raises(KernelError) as excinfo:
        await queries.get_grant_for_subject(
            grant.id, subject_type="identity", subject_id="another-user"
        )
    assert excinfo.value.code == "archive.grant_forbidden"

    async with uow_factory() as uow:
        row = await uow.session.get(ArchiveItem, uuid.UUID(item.id))
        assert row is not None
        row.version += 1
        await uow.commit()
    with pytest.raises(KernelError) as excinfo:
        await ResolveDownloadLinks(archive_context)(grant.id)
    assert excinfo.value.code == "archive.manifest_mismatch"


async def test_delivery_activity_records_only_safe_attempt_facts(
    archive_context: CommandContext, uow_factory: UoWFactory
) -> None:
    item = await _active_item(archive_context)
    grant = await _active_grant(archive_context, item.id)
    result = await ResolveDownloadLinks(archive_context)(grant.id)
    assert result.links[0].status == "proxy"
    assert result.links[0].proxy_ticket
    assert result.links[0].redirect_url is None

    async with uow_factory() as uow:
        attempts = (await uow.session.execute(select(ArchiveDeliveryAttempt))).scalars().all()
        assert len(attempts) == 1
        assert not hasattr(attempts[0], "redirect_url")
        assert not hasattr(attempts[0], "headers")

    # Replays refresh the opaque provider reference and do not create another
    # attempt or persist the short-lived ticket.
    replay = await ResolveDownloadLinks(archive_context)(grant.id)
    assert replay.links[0].attempt_id == result.links[0].attempt_id
    async with uow_factory() as uow:
        assert len((await uow.session.execute(select(ArchiveDeliveryAttempt))).scalars().all()) == 1


async def test_grant_expiry_revoke_and_manual_attempt_are_named_transitions(
    archive_context: CommandContext, uow_factory: UoWFactory, clock: Any
) -> None:
    item = await _active_item(archive_context)
    grant = await _active_grant(archive_context, item.id)
    attempt = await RecordDeliveryAttempt(archive_context)(
        RecordDeliveryAttemptInput(
            grant_id=grant.id,
            item_id=item.id,
            provider_key="archive.fake",
            attempt_number=1,
            status="failed",
            reason_code="timeout",
        )
    )
    assert attempt.reason_code == "timeout"

    revoked = await RevokeDownloadGrant(archive_context)(
        GrantStateInput(grant_id=grant.id, expected_version=grant.version)
    )
    assert revoked.status == "revoked"
    with pytest.raises(KernelError) as excinfo:
        await ResolveDownloadLinks(archive_context)(revoked.id)
    assert excinfo.value.code == "archive.grant_forbidden"

    # A separate grant demonstrates the explicit expiry command without
    # relying on a query-side clock mutation.
    item_two = await _active_item(archive_context, key="part-2", part=2)
    expiring = await IssueDownloadGrant(archive_context)(
        IssueDownloadGrantInput(
            subject_type="identity",
            subject_id="user-1",
            target_type="work",
            target_id="work-2",
            item_ids=(item_two.id,),
            manifest_version="work.v1",
            expires_at=clock.utc_now() + timedelta(seconds=2),
            idempotency_key="consumption-2",
        )
    )
    await ActivateDownloadGrant(archive_context)(expiring.id, expected_version=expiring.version)
    clock.advance(timedelta(seconds=3))
    expired = await ExpireDownloadGrant(archive_context)(expiring.id, expected_version=2)
    assert expired.status == "expired"

    async with uow_factory() as uow:
        grants = (await uow.session.execute(select(ArchiveDownloadGrant))).scalars().all()
        events = (await uow.session.execute(select(OutboxMessage))).scalars().all()
    assert len(grants) == 2
    assert all("locator" not in str(event.envelope.payload).lower() for event in events)
