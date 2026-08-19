"""Administrator membership workbench contracts."""

from __future__ import annotations

from typing import Any

import pytest


async def _register(client: Any, uow_factory: Any, clock: Any, username: str) -> Any:
    from inc.capabilities.identity.commands import CommandContext as IdentityCommandContext
    from inc.capabilities.identity.commands import RegisterLocalUser
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    result = await RegisterLocalUser(
        IdentityCommandContext(
            uow_factory=uow_factory,
            clock=clock,
            hasher=services.hasher,
            outbox=services.outbox,
            audit_actor_id="system",
            audit_trace_id="test",
        )
    )(username=username, email=f"{username}@example.com", password="password-123456")
    return result.subject, await _mint_token_for(services, result.subject.id)


@pytest.fixture
async def program(uow_factory: Any) -> None:
    from inc.capabilities.points.models import PointsProgram

    async with uow_factory() as uow:
        uow.session.add(
            PointsProgram(
                program_key="credit", display_name="Credit", unit="points", status="active"
            )
        )
        await uow.commit()


async def test_membership_admin_summary_levels_and_subscription(
    client: Any, admin_token: str, uow_factory: Any, clock: Any, program: None
) -> None:
    subject, _ = await _register(client, uow_factory, clock, "membership-admin-target")
    headers = {"Authorization": f"Bearer {admin_token}"}

    levels = await client.get("/api/v1/admin/membership/levels", headers=headers)
    assert levels.status_code == 200, levels.text
    basic = next(item for item in levels.json() if item["level_key"] == "basic")

    created_level = await client.post(
        "/api/v1/admin/membership/levels",
        json={
            "level_key": "pro",
            "display_name": "Pro",
            "tier_rank": 2,
            "cycle_days": 30,
            "grant_points": 500,
            "renewal_allowed": True,
        },
        headers=headers,
    )
    assert created_level.status_code == 200, created_level.text
    assert created_level.json()["level_key"] == "pro"

    summary = await client.get("/api/v1/admin/membership/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    assert summary.json()["level_count"] >= 1

    prepared = await client.post(
        "/api/v1/admin/membership/cycles/prepare",
        json={
            "subject_type": "identity",
            "subject_id": subject.id,
            "level_key": basic["level_key"],
            "auto_renew": False,
            "source_type": "admin",
            "source_ref": "membership-admin-1",
            "idempotency_key": "membership-admin-1",
        },
        headers=headers,
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["subject_id"] == subject.id
    assert prepared.json()["state"] == "prepared"

    listed = await client.get("/api/v1/admin/membership/subscriptions", headers=headers)
    assert listed.status_code == 200, listed.text
    item = next(row for row in listed.json()["items"] if row["subject_id"] == subject.id)
    assert item["subject"]["username"] == "membership-admin-target"
    assert item["status"] == "pending_activation"


async def test_membership_level_patch_rejects_explicit_null(client: Any, admin_token: str) -> None:
    response = await client.patch(
        "/api/v1/admin/membership/levels/basic",
        json={"expected_version": 1, "display_name": None},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 422
