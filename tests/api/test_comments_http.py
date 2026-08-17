"""Public and administrator comments HTTP contract."""

from __future__ import annotations

import uuid
from typing import Any

from inc.capabilities.comments.models import Comment


async def _seed_pending(client: Any, clock: Any) -> uuid.UUID:
    comment_id = uuid.uuid4()
    services = client.app.state.services
    async with services.uow_factory() as uow:
        uow.session.add(
            Comment(
                id=comment_id,
                target_type="post",
                target_id="11111111-1111-1111-1111-111111111111",
                author_type="identity",
                author_id="author-1",
                body="Please review",
                status="pending",
                submitted_at=clock.utc_now(),
            )
        )
        await uow.commit()
    return comment_id


async def test_public_read_and_admin_moderation(
    client: Any,
    admin_token: str,
    clock: Any,
) -> None:
    comment_id = await _seed_pending(client, clock)
    public_url = "/api/v1/content/post/11111111-1111-1111-1111-111111111111/comments"
    assert (await client.get(public_url)).json()["total"] == 0

    headers = {"Authorization": f"Bearer {admin_token}"}
    listed = await client.get(
        "/api/v1/admin/comments", params={"status": "pending"}, headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["id"] == str(comment_id)
    assert "author" in listed.json()["items"][0]
    assert "target" in listed.json()["items"][0]

    approved = await client.post(f"/api/v1/admin/comments/{comment_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "published"
    assert (await client.get(public_url)).json()["total"] == 1


async def test_comments_authentication_boundaries(client: Any) -> None:
    target = "11111111-1111-1111-1111-111111111111"
    assert (await client.get(f"/api/v1/content/post/{target}/comments")).status_code == 200
    assert (
        await client.post(f"/api/v1/content/post/{target}/comments", json={"body": "Anonymous"})
    ).status_code == 401
    assert (await client.get("/api/v1/admin/comments")).status_code == 401
