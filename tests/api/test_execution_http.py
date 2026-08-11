"""Admin read access to kernel execution records."""

from __future__ import annotations

from typing import Any


async def test_execution_entries_are_visible_to_audit_read_admin(
    client: Any, admin_token: str
) -> None:
    response = await client.get(
        "/api/v1/admin/execution/entries",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] >= 0
    assert (
        {"id", "kind", "key", "status", "occurred_at"} <= set(page["items"][0])
        if page["items"]
        else True
    )
