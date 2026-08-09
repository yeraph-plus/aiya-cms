"""Audit admin router tests.

Contract source: context/spec/http-openapi.md §5/§12,
context/spec/capabilities/audit.md.
"""

from __future__ import annotations

from typing import Any


async def test_audit_entries_listing_after_audited_action(
    client: Any, admin_token: str, uow_factory: Any, clock: Any
) -> None:
    from inc.capabilities.identity.commands import (
        CommandContext as IdentityCommandContext,
    )
    from inc.capabilities.identity.commands import (
        RegisterLocalUser,
    )

    services = client.app.state.services
    identity_ctx = IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )
    await RegisterLocalUser(identity_ctx)(
        username="audited", email="audited@example.com", password="password-123456"
    )
    # workers are disabled in tests; deliver the outbox synchronously
    await services.dispatcher.dispatch_cycle()

    headers = {"Authorization": f"Bearer {admin_token}"}
    entries = await client.get(
        "/api/v1/admin/audit/entries",
        params={"action": "identity.user.register"},
        headers=headers,
    )
    assert entries.status_code == 200, entries.text
    page = entries.json()
    assert page["total"] >= 1
    entry = page["items"][0]
    assert entry["action"] == "identity.user.register"
    assert entry["target_type"] == "user"
    assert entry["outcome"] == "success"

    empty = await client.get(
        "/api/v1/admin/audit/entries",
        params={"action": "no.such.action"},
        headers=headers,
    )
    assert empty.status_code == 200
    assert empty.json()["total"] == 0


async def test_audit_entries_require_capability(client: Any, uow_factory: Any, clock: Any) -> None:
    from inc.capabilities.identity.commands import (
        CommandContext as IdentityCommandContext,
    )
    from inc.capabilities.identity.commands import (
        RegisterLocalUser,
    )
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    identity_ctx = IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )
    user = await RegisterLocalUser(identity_ctx)(
        username="noaudit", email="noaudit@example.com", password="password-123456"
    )
    token = await _mint_token_for(services, user.subject.id)
    denied = await client.get(
        "/api/v1/admin/audit/entries", headers={"Authorization": f"Bearer {token}"}
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "api.forbidden"
