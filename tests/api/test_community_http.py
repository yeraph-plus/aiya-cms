"""Community HTTP contract tests."""

from __future__ import annotations

from typing import Any


async def test_community_public_routes_and_idempotent_writes(client: Any, admin_token: str) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    tag_response = await client.post(
        "/api/v1/admin/community/tags",
        headers=headers,
        json={"kind": "primary", "name": "HTTP", "slug": "http"},
    )
    assert tag_response.status_code == 200, tag_response.text
    tag_id = tag_response.json()["id"]
    create_headers = {**headers, "Idempotency-Key": "http-discussion-1"}
    payload = {
        "template_key": "general",
        "title": "HTTP discussion",
        "body": "A public body",
        "tag_ids": [tag_id],
    }
    first = await client.post("/api/v1/community/discussions", headers=create_headers, json=payload)
    assert first.status_code == 200, first.text
    replay = await client.post(
        "/api/v1/community/discussions", headers=create_headers, json=payload
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]

    tags = await client.get("/api/v1/community/tags")
    assert tags.status_code == 200
    assert tags.json()[0]["published_discussion_count"] == 1
    listing = await client.get("/api/v1/community/discussions?q=public%20body")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    detail = await client.get(f"/api/v1/community/discussions/by-slug/{first.json()['slug']}")
    assert detail.status_code == 200
    posts = await client.get(f"/api/v1/community/discussions/{first.json()['id']}/posts")
    assert posts.status_code == 200
    assert posts.json()["total"] == 1


async def test_community_requires_idempotency_key_for_user_writes(
    client: Any, admin_token: str
) -> None:
    response = await client.post(
        "/api/v1/community/discussions",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"title": "Missing key", "body": "body", "tag_ids": []},
    )
    assert response.status_code == 422
