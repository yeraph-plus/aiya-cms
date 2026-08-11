"""Settings admin router tests.

Contract source: context/spec/http-openapi.md §5/§12,
context/spec/capabilities/settings.md.
"""

from __future__ import annotations

from typing import Any


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


async def test_groups_list_get_update_reset(client: Any, admin_token: str) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}

    groups = await client.get("/api/v1/admin/settings/groups", headers=headers)
    assert groups.status_code == 200, groups.text
    keys = {item["group_key"] for item in groups.json()}
    assert {"general", "seo", "notification"} <= keys

    general = await client.get("/api/v1/admin/settings/groups/general", headers=headers)
    assert general.status_code == 200
    assert general.json()["values"]["site_tagline"] == ""
    assert {field["slug"] for field in general.json()["fields"]} == {
        "site_tagline",
        "site_logo_asset_id",
        "default_locale",
        "default_timezone",
        "maintenance_mode",
    }
    version = general.json()["version"]

    updated = await client.put(
        "/api/v1/admin/settings/groups/general",
        json={
            "expected_version": version,
            "values": {"site_tagline": "hello cms", "maintenance_mode": True},
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["values"]["site_tagline"] == "hello cms"
    assert updated.json()["version"] > version

    conflict = await client.put(
        "/api/v1/admin/settings/groups/general",
        json={"expected_version": version, "values": {"site_tagline": "stale"}},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "settings.version_conflict"

    unknown_field = await client.put(
        "/api/v1/admin/settings/groups/general",
        json={"expected_version": updated.json()["version"], "values": {"no_such_field": "x"}},
        headers=headers,
    )
    assert unknown_field.status_code == 422
    assert unknown_field.json()["code"] == "kernel.validation_error"

    unknown_group = await client.get("/api/v1/admin/settings/groups/nope", headers=headers)
    assert unknown_group.status_code == 422
    assert unknown_group.json()["code"] == "settings.unknown_group"

    reset = await client.post("/api/v1/admin/settings/groups/general/reset", headers=headers)
    assert reset.status_code == 200
    assert reset.json()["values"]["site_tagline"] == ""


async def test_notification_group_keeps_sensitive_out_of_public_projection(
    client: Any, admin_token: str
) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    current = await client.get("/api/v1/admin/settings/groups/notification", headers=headers)
    assert current.status_code == 200
    updated = await client.put(
        "/api/v1/admin/settings/groups/notification",
        json={
            "expected_version": current.json()["version"],
            "values": {
                "smtp_host": "smtp.example.com",
                "smtp_password": "s3cret",
                "smtp2go_api_key": "api-secret",
            },
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    payload = updated.json()
    assert "smtp_password" not in payload["values"]
    assert "smtp2go_api_key" not in payload["values"]
    assert payload["sensitive_configured"]["smtp_password"] is True
    assert payload["sensitive_configured"]["smtp2go_api_key"] is True

    fetched = await client.get("/api/v1/admin/settings/groups/notification", headers=headers)
    assert fetched.status_code == 200
    assert "smtp_password" not in fetched.json()["values"]
    assert "smtp2go_api_key" not in fetched.json()["values"]
    assert fetched.json()["sensitive_configured"]["smtp_password"] is True
    assert fetched.json()["sensitive_configured"]["smtp2go_api_key"] is True

    cleared = await client.put(
        "/api/v1/admin/settings/groups/notification",
        json={
            "expected_version": payload["version"],
            "values": {},
            "clear_sensitive_fields": ["smtp_password"],
        },
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["sensitive_configured"]["smtp_password"] is False
    assert cleared.json()["sensitive_configured"]["smtp2go_api_key"] is True


async def test_settings_routes_require_capability(
    client: Any, uow_factory: Any, clock: Any
) -> None:
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    user = await _register_user(uow_factory, clock, services, "nosettings")
    token = await _mint_token_for(services, user.subject.id)
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/v1/admin/settings/groups", headers=headers)).status_code == 403
    denied = await client.put(
        "/api/v1/admin/settings/groups/general",
        json={"expected_version": 0, "values": {"site_tagline": "x"}},
        headers=headers,
    )
    assert denied.status_code == 403
