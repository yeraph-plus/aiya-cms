"""Assets HTTP integration tests.

Contract source: context/spec/capabilities/assets.md §8, http-openapi.md §12.
"""

from __future__ import annotations

import uuid
from typing import Any


async def test_asset_lifecycle_via_api(client: Any, admin_token: str, clock: Any) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}

    intent = await client.post(
        "/api/v1/admin/assets/upload-intents",
        json={
            "provider_key": "dev_memory",
            "mime_types": ["image/png"],
            "content_length_max": 10_000_000,
        },
        headers=headers,
    )
    assert intent.status_code == 200, intent.text
    intent_body = intent.json()
    assert intent_body["object_key"].startswith("uploads/")

    # upload the object bytes into the dev store (the dev provider is
    # exercised through the same store the container bound)
    app = client.app
    dev_storage = app.state.services.dev_storage
    assert dev_storage is not None
    dev_storage._objects[intent_body["object_key"]] = b"\x89PNG fake-bytes"

    finalized = await client.post(
        f"/api/v1/admin/assets/upload-intents/{intent_body['intent_id']}/finalize",
        headers=headers,
    )
    assert finalized.status_code == 200
    assert finalized.json()["state"] == "pending"

    await app.state.container.services.runner.run_due()

    # no list endpoint yet; fetch by id after resolving from the store
    from sqlalchemy import select

    from inc.capabilities.assets.models import AssetObject

    async with app.state.services.uow_factory() as uow:
        row = (
            (
                await uow.session.execute(
                    select(AssetObject).where(AssetObject.object_key == intent_body["object_key"])
                )
            )
            .scalars()
            .first()
        )
        assert row is not None and row.state == "ready"
        asset_id = str(row.id)

    fetched = await client.get(f"/api/v1/admin/assets/{asset_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["state"] == "ready"
    assert fetched.json()["mime_type"] == "image/png"

    url = await client.get(
        f"/api/v1/admin/assets/{asset_id}/url",
        params={"expires_in_seconds": 120},
        headers=headers,
    )
    assert url.status_code == 200
    assert "expires=120" in url.json()["url"]

    deleted = await client.delete(f"/api/v1/admin/assets/{asset_id}", headers=headers)
    assert deleted.status_code == 204
    await app.state.container.services.runner.run_due()
    async with app.state.services.uow_factory() as uow:
        row = (
            (
                await uow.session.execute(
                    select(AssetObject).where(AssetObject.id == uuid.UUID(asset_id))
                )
            )
            .scalars()
            .first()
        )
    assert row is not None and row.external_deleted_at is not None


async def test_assets_read_requires_permission(client: Any, admin_token: str) -> None:
    response = await client.get("/api/v1/admin/assets/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 401


async def test_unknown_provider_is_validation_error(client: Any, admin_token: str) -> None:
    response = await client.post(
        "/api/v1/admin/assets/upload-intents",
        json={
            "provider_key": "nope",
            "mime_types": ["image/png"],
            "content_length_max": 1000,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "assets.unknown_provider"


async def test_intent_finalize_requires_upload_permission(
    client: Any, uow_factory: Any, clock: Any
) -> None:
    app = client.app
    services = app.state.services
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
    result = await RegisterLocalUser(identity_ctx)(
        username="viewer", email="viewer@example.com", password="password-123456"
    )
    from tests.api.conftest import _mint_token_for

    token = await _mint_token_for(services, result.subject.id)
    response = await client.post(
        f"/api/v1/admin/assets/upload-intents/{'0' * 32}/finalize",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "api.forbidden"
