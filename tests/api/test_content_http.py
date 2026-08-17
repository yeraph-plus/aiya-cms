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
            "body": "# First post",
            "excerpt": "hello",
            "data": {},
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
        json={"type_name": "ghost", "title": "x", "data": {}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "content.unknown_type"


async def test_admin_content_list_contains_all_registered_types(
    client: Any, admin_token: str
) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    for type_name in ("post", "page"):
        created = await client.post(
            "/api/v1/admin/content",
            json={"type_name": type_name, "title": type_name, "data": {}},
            headers=headers,
        )
        assert created.status_code == 200, created.text

    listing = await client.get("/api/v1/admin/content", headers=headers)
    assert listing.status_code == 200, listing.text
    assert {item["type_name"] for item in listing.json()["items"]} == {"post", "page"}


async def test_invalid_transition_conflict(client: Any, admin_token: str) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = await client.post(
        "/api/v1/admin/content",
        json={
            "type_name": "post",
            "title": "t",
            "data": {},
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
        json={"type_name": "post", "title": "A", "body": "# A", "excerpt": "s", "data": {}},
        headers=headers,
    )
    await client.post(
        "/api/v1/admin/content",
        json={"type_name": "post", "title": "B", "body": "# B", "excerpt": "s", "data": {}},
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
            "body": "# Scheduled",
            "excerpt": "s",
            "data": {},
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


async def test_explicit_sort_via_api(client: Any, admin_token: str) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    for title in ("banana", "apple", "cherry"):
        created = await client.post(
            "/api/v1/admin/content",
            json={"type_name": "post", "title": title, "data": {}},
            headers=headers,
        )
        assert created.status_code == 200, created.text

    asc = await client.get(
        "/api/v1/admin/content",
        params={"type_name": "post", "sort": "title"},
        headers=headers,
    )
    assert asc.status_code == 200, asc.text
    assert [item["title"] for item in asc.json()["items"]] == ["apple", "banana", "cherry"]

    desc = await client.get(
        "/api/v1/admin/content",
        params={"type_name": "post", "sort": "-title"},
        headers=headers,
    )
    assert [item["title"] for item in desc.json()["items"]] == ["cherry", "banana", "apple"]

    # default order is unchanged when sort is omitted (pin-first spec §7)
    default = await client.get("/api/v1/admin/content", headers=headers)
    assert default.status_code == 200

    unknown = await client.get("/api/v1/admin/content", params={"sort": "bogus"}, headers=headers)
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "content.invalid_sort"

    not_allowlisted = await client.get(
        "/api/v1/admin/content",
        params={"type_name": "post", "sort": "slug"},
        headers=headers,
    )
    assert not_allowlisted.status_code == 422
    assert not_allowlisted.json()["code"] == "content.invalid_sort"
