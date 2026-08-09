"""Identity admin router tests.

Contract source: context/spec/http-openapi.md §5/§12,
context/spec/capabilities/identity.md §8.
"""

from __future__ import annotations

import uuid
from typing import Any


def _identity_ctx(uow_factory: Any, clock: Any, services: Any) -> Any:
    from inc.capabilities.identity.commands import CommandContext as IdentityCommandContext

    return IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )


async def _register(uow_factory: Any, clock: Any, services: Any, username: str) -> Any:
    from inc.capabilities.identity.commands import RegisterLocalUser

    return await RegisterLocalUser(_identity_ctx(uow_factory, clock, services))(
        username=username,
        email=f"{username}@example.com",
        password="password-123456",
    )


async def test_list_and_get_users(
    client: Any, admin_token: str, uow_factory: Any, clock: Any
) -> None:
    services = client.app.state.services
    created = await _register(uow_factory, clock, services, "listed")
    headers = {"Authorization": f"Bearer {admin_token}"}

    listing = await client.get("/api/v1/admin/users", headers=headers)
    assert listing.status_code == 200, listing.text
    page = listing.json()
    assert page["total"] >= 2
    assert page["page"] == 1
    usernames = {item["username"] for item in page["items"]}
    assert {"admin", "listed"} <= usernames

    got = await client.get(f"/api/v1/admin/users/{created.subject.id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["email"] == "listed@example.com"

    missing = await client.get(f"/api/v1/admin/users/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "identity.not_found"

    filtered = await client.get("/api/v1/admin/users", params={"status": "banned"}, headers=headers)
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 0


async def test_ban_blocks_bearer_and_delete_marks_status(
    client: Any, admin_token: str, uow_factory: Any, clock: Any
) -> None:
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    created = await _register(uow_factory, clock, services, "target")
    user_token = await _mint_token_for(services, created.subject.id)
    user_headers = {"Authorization": f"Bearer {user_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    assert (await client.get("/api/v1/auth/me", headers=user_headers)).status_code == 200

    banned = await client.post(
        f"/api/v1/admin/users/{created.subject.id}/ban",
        json={"reason": "spam"},
        headers=admin_headers,
    )
    assert banned.status_code == 200, banned.text
    assert banned.json()["status"] == "banned"

    # ban triggers the security event but the bearer check re-reads status
    assert (await client.get("/api/v1/auth/me", headers=user_headers)).status_code == 401

    deleted = await client.delete(
        f"/api/v1/admin/users/{created.subject.id}", headers=admin_headers
    )
    assert deleted.status_code == 204
    got = await client.get(f"/api/v1/admin/users/{created.subject.id}", headers=admin_headers)
    assert got.json()["status"] == "deleted"


async def test_users_routes_require_capability(client: Any, uow_factory: Any, clock: Any) -> None:
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    created = await _register(uow_factory, clock, services, "plain")
    token = await _mint_token_for(services, created.subject.id)
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/v1/admin/users", headers=headers)).status_code == 403
    assert (
        await client.post(f"/api/v1/admin/users/{created.subject.id}/ban", json={}, headers=headers)
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/admin/users/{created.subject.id}", headers=headers)
    ).status_code == 403
    assert (await client.get("/api/v1/admin/users", headers=headers)).json()[
        "code"
    ] == "api.forbidden"


async def test_unban_restores_active_status(
    client: Any, admin_token: str, uow_factory: Any, clock: Any
) -> None:
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    created = await _register(uow_factory, clock, services, "unbanee")
    user_token = await _mint_token_for(services, created.subject.id)
    user_headers = {"Authorization": f"Bearer {user_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    banned = await client.post(
        f"/api/v1/admin/users/{created.subject.id}/ban",
        json={"reason": "spam"},
        headers=admin_headers,
    )
    assert banned.status_code == 200
    assert banned.json()["status"] == "banned"
    assert (await client.get("/api/v1/auth/me", headers=user_headers)).status_code == 401

    unbanned = await client.post(
        f"/api/v1/admin/users/{created.subject.id}/unban", headers=admin_headers
    )
    assert unbanned.status_code == 200, unbanned.text
    assert unbanned.json()["status"] == "active"

    # the security event already went out with the unban; the bearer re-reads
    # status so the same token authenticates again immediately
    assert (await client.get("/api/v1/auth/me", headers=user_headers)).status_code == 200


async def test_unban_rejects_non_banned_and_unknown(
    client: Any, admin_token: str, uow_factory: Any, clock: Any
) -> None:
    services = client.app.state.services
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    created = await _register(uow_factory, clock, services, "never-banned")
    conflict = await client.post(
        f"/api/v1/admin/users/{created.subject.id}/unban", headers=admin_headers
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "identity.not_banned"

    missing = await client.post(f"/api/v1/admin/users/{uuid.uuid4()}/unban", headers=admin_headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "identity.not_found"


async def test_unban_route_requires_capability(client: Any, uow_factory: Any, clock: Any) -> None:
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    created = await _register(uow_factory, clock, services, "no-unban")
    token = await _mint_token_for(services, created.subject.id)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(f"/api/v1/admin/users/{created.subject.id}/unban", headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "api.forbidden"
