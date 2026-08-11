from __future__ import annotations

import uuid


async def test_public_content_type_route_is_segregated(client):
    response = await client.get("/api/v1/content/post")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"items", "total", "page", "size"}


async def test_engagement_writes_require_authentication(client):
    content_id = uuid.uuid4()
    response = await client.put(f"/api/v1/content/post/{content_id}/like")
    assert response.status_code == 401


async def test_dashboard_requires_admin_capability(client):
    response = await client.get("/api/v1/admin/dashboard")
    assert response.status_code == 401


async def test_dashboard_aggregates_enabled_capability_stats(client, admin_token):
    response = await client.get(
        "/api/v1/admin/dashboard?window=7d",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["window"] == "7d"
    assert "identity" in payload["capabilities"]
    assert "engagement" in payload["capabilities"]
