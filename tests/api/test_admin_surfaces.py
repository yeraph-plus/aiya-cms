from __future__ import annotations


async def test_assets_exposes_configured_bucket_names(client, admin_token):
    response = await client.get(
        "/api/v1/admin/assets/buckets",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["buckets"] == ["aiya-assets", "aiya-avatars"]


async def test_admin_users_profile_patch_is_semantic(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    listed = await client.get("/api/v1/admin/users", headers=headers)
    assert listed.status_code == 200
    user_id = listed.json()["items"][0]["id"]
    updated = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        headers=headers,
        json={"display_name": "Updated Admin"},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Updated Admin"
