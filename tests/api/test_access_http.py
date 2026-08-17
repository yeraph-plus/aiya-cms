"""Access admin router tests.

Contract source: context/spec/http-openapi.md §5/§12,
context/spec/capabilities/access.md.
"""

from __future__ import annotations

from typing import Any


def _access_ctx(uow_factory: Any, clock: Any, services: Any) -> Any:
    from inc.capabilities.access.commands import CommandContext as AccessCommandContext
    from tests.api.conftest import _always_exists

    return AccessCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        outbox=services.outbox,
        permissions=services.permission_registry,
        subject_exists=_always_exists(),
        audit_actor_id="system",
        audit_trace_id="test",
    )


async def _register_user(uow_factory: Any, clock: Any, services: Any, username: str) -> Any:
    from inc.capabilities.identity.commands import (
        CommandContext as IdentityCommandContext,
    )
    from inc.capabilities.identity.commands import (
        RegisterLocalUser,
    )

    identity_ctx = IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )
    return await RegisterLocalUser(identity_ctx)(
        username=username,
        email=f"{username}@example.com",
        password="password-123456",
    )


async def test_role_lifecycle_and_grant_effect(
    client: Any, admin_token: str, uow_factory: Any, clock: Any
) -> None:
    from inc.capabilities.access.commands import ReplaceRoleCapabilities
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    headers = {"Authorization": f"Bearer {admin_token}"}

    caps = await client.get("/api/v1/admin/capabilities", headers=headers)
    assert caps.status_code == 200
    assert "content.write" in caps.json()["keys"]

    created = await client.post(
        "/api/v1/admin/roles",
        json={"name": "Custom editor", "slug": "custom-editor"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    role = created.json()
    assert role["slug"] == "custom-editor"

    duplicate = await client.post(
        "/api/v1/admin/roles",
        json={"name": "Custom editor 2", "slug": "custom-editor"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    roles = await client.get("/api/v1/admin/roles", headers=headers)
    assert roles.status_code == 200
    assert "custom-editor" in {item["slug"] for item in roles.json()}

    # bind content.write to the role (command layer; no HTTP surface)
    await ReplaceRoleCapabilities(_access_ctx(uow_factory, clock, services))(
        role_id=role["id"], capability_keys=("content.write",)
    )

    user = await _register_user(uow_factory, clock, services, "grantee")
    assigned = await client.post(
        f"/api/v1/admin/roles/{role['id']}/assign",
        json={"subject_type": "identity", "subject_id": user.subject.id},
        headers=headers,
    )
    assert assigned.status_code == 200, assigned.text
    assert role["id"] in assigned.json()["roles"]

    token = await _mint_token_for(services, user.subject.id)
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert "content.write" in me.json()["capabilities"]

    revoked = await client.post(
        f"/api/v1/admin/roles/{role['id']}/revoke",
        json={"subject_type": "identity", "subject_id": user.subject.id},
        headers=headers,
    )
    assert revoked.status_code == 204

    # decisions are read live: revocation takes effect with the same token
    me_after = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert "content.write" not in me_after.json()["capabilities"]


async def test_roles_routes_require_capability(client: Any, uow_factory: Any, clock: Any) -> None:
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    user = await _register_user(uow_factory, clock, services, "noroles")
    token = await _mint_token_for(services, user.subject.id)
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/v1/admin/roles", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/admin/capabilities", headers=headers)).status_code == 403
    assert (
        await client.post("/api/v1/admin/roles", json={"name": "x", "slug": "x"}, headers=headers)
    ).status_code == 403
