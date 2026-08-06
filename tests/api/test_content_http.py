"""Content HTTP integration tests.

Contract source: context/spec/http-openapi.md §7/§12, capabilities/content.md §11.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any


async def test_content_lifecycle_via_api(client: Any, admin_token: str, clock: Any) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/admin/content",
        json={
            "type_name": "post",
            "title": "First post",
            "slug": "first-post",
            "data": {"summary": "hello"},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    content = created.json()
    assert content["status"] == "draft"
    content_id = content["id"]

    scheduled = await client.post(
        f"/api/v1/admin/content/{content_id}/schedule",
        json={"publish_at": (clock.utc_now() + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["status"] == "scheduled"
    assert scheduled.json()["schedule_version"] == 1

    published = await client.post(f"/api/v1/admin/content/{content_id}/publish", headers=headers)
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_at"] is not None

    archived = await client.post(f"/api/v1/admin/content/{content_id}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    listing = await client.get(
        "/api/v1/admin/content", params={"page": 1, "size": 5}, headers=headers
    )
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == content_id


async def test_unknown_type_is_validation_error(client: Any, admin_token: str) -> None:
    response = await client.post(
        "/api/v1/admin/content",
        json={"type_name": "ghost", "title": "x", "slug": "x-1", "data": {}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 500
    assert response.json()["code"] == "content.unknown_type"


async def test_invalid_transition_conflict(client: Any, admin_token: str) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/admin/content",
        json={
            "type_name": "post",
            "title": "t",
            "slug": "t-1",
            "data": {"summary": "s"},
        },
        headers=headers,
    )
    content_id = created.json()["id"]
    rejected = await client.post(
        f"/api/v1/admin/content/{content_id}/reject",
        json={"reason": "nope"},
        headers=headers,
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "content.invalid_transition"


async def test_pin_pagination_stable_through_api(client: Any, admin_token: str, clock: Any) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    first = await client.post(
        "/api/v1/admin/content",
        json={"type_name": "post", "title": "A", "slug": "pin-a", "data": {"summary": "s"}},
        headers=headers,
    )
    await client.post(
        "/api/v1/admin/content",
        json={"type_name": "post", "title": "B", "slug": "pin-b", "data": {"summary": "s"}},
        headers=headers,
    )
    first_id = first.json()["id"]
    for content_id in (first_id,):
        await client.post(f"/api/v1/admin/content/{content_id}/publish", headers=headers)
    await client.post(
        f"/api/v1/admin/content/{first_id}/pin",
        json={"is_pinned": True, "pin_rank": 5},
        headers=headers,
    )
    listing = await client.get(
        "/api/v1/admin/content", params={"page": 1, "size": 10}, headers=headers
    )
    items = listing.json()["items"]
    assert items[0]["id"] == first_id
    assert items[0]["is_pinned"] is True


async def test_scheduled_publish_via_scanner(client: Any, admin_token: str, clock: Any) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/admin/content",
        json={
            "type_name": "post",
            "title": "Scheduled",
            "slug": "sched-1",
            "data": {"summary": "s"},
        },
        headers=headers,
    )
    content_id = created.json()["id"]
    await client.post(
        f"/api/v1/admin/content/{content_id}/schedule",
        json={"publish_at": (clock.utc_now() + timedelta(minutes=1)).isoformat()},
        headers=headers,
    )
    clock.advance(timedelta(minutes=2))
    app = client.app
    await app.state.container.services.scanner.scan_once()
    await app.state.container.services.runner.run_due()
    fetched = await client.get(f"/api/v1/admin/content/{content_id}", headers=headers)
    assert fetched.json()["status"] == "published"
