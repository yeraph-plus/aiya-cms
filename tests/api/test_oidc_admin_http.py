"""Administrator OIDC client management HTTP contract."""

from __future__ import annotations

from typing import Any


async def test_admin_manages_static_oidc_clients(client: Any, admin_token: str) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/admin/oidc/clients",
        headers=headers,
        json={
            "name": "Admin test SPA",
            "client_type": "public",
            "client_id": "admin-test-spa",
            "redirect_uris": ["http://localhost:5173/callback"],
            "post_logout_redirect_uris": ["http://localhost:5173/logged-out"],
            "allowed_scopes": ["openid", "profile", "email"],
            "allowed_audiences": ["aiya-admin"],
            "trusted": True,
            "allow_refresh": False,
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["client"]["client_id"] == "admin-test-spa"
    assert created.json()["client_secret"] is None

    listed = await client.get("/api/v1/admin/oidc/clients", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["client_id"] for item in listed.json()] == ["admin-test-spa"]

    disabled = await client.post(
        "/api/v1/admin/oidc/clients/admin-test-spa/disable", headers=headers
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    enabled = await client.post("/api/v1/admin/oidc/clients/admin-test-spa/enable", headers=headers)
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "active"


async def test_oidc_client_admin_surface_requires_authentication(client: Any) -> None:
    assert (await client.get("/api/v1/admin/oidc/clients")).status_code == 401
