"""Assets HTTP integration tests.

Contract source: context/spec/capabilities/assets.md §8, http-openapi.md §12.
"""

from __future__ import annotations

import asyncio
import os
import urllib.request
import uuid
from typing import Any

import httpx
import pytest

from inc.adapters.assets.s3 import S3ObjectStorage, S3Settings

RUSTFS_ENDPOINT = os.environ.get("AIYA_TEST_S3_ENDPOINT", "http://127.0.0.1:9000").rstrip("/")
RUSTFS_BUCKET = os.environ.get("AIYA_TEST_S3_BUCKET", "aiya-assets")
RUSTFS_ACCESS_KEY = os.environ.get("RUSTFS_ACCESS_KEY", "rustfsadmin")
RUSTFS_SECRET_KEY = os.environ.get("RUSTFS_SECRET_KEY", "rustfsadmin")


def _rustfs_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{RUSTFS_ENDPOINT}/health", timeout=1) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - unavailable integration service means skip
        return False


async def _ensure_bucket() -> None:
    settings = S3Settings.from_values(
        {
            "s3_endpoint_url": RUSTFS_ENDPOINT,
            "s3_virtual_host_url": RUSTFS_ENDPOINT,
            "s3_bucket": RUSTFS_BUCKET,
            "s3_region": "us-east-1",
            "s3_addressing_style": "path",
            "s3_access_key_id": RUSTFS_ACCESS_KEY,
            "s3_secret_access_key": RUSTFS_SECRET_KEY,
        }
    )
    client = S3ObjectStorage._client(settings)

    def create() -> None:
        try:
            client.create_bucket(Bucket=RUSTFS_BUCKET)
        except Exception as exc:  # noqa: BLE001 - already-created is expected
            response = getattr(exc, "response", {})
            code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
            if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise

    await asyncio.to_thread(create)


@pytest.mark.skipif(not _rustfs_ready(), reason="RustFS S3 endpoint is not serving")
async def test_asset_lifecycle_via_api(client: Any, admin_token: str, clock: Any) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    await _ensure_bucket()

    configured = await client.put(
        "/api/v1/admin/settings/groups/object_storage",
        json={
            "expected_version": 0,
            "values": {
                "s3_endpoint_url": RUSTFS_ENDPOINT,
                "s3_virtual_host_url": RUSTFS_ENDPOINT,
                "s3_bucket": RUSTFS_BUCKET,
                "s3_region": "us-east-1",
                "s3_addressing_style": "path",
                "s3_access_key_id": RUSTFS_ACCESS_KEY,
                "s3_secret_access_key": RUSTFS_SECRET_KEY,
            },
        },
        headers=headers,
    )
    assert configured.status_code == 200, configured.text

    intent = await client.post(
        "/api/v1/admin/assets/upload-intents",
        json={
            "provider_key": "s3",
            "mime_types": ["image/png"],
            "content_length_max": 10_000_000,
        },
        headers=headers,
    )
    assert intent.status_code == 200, intent.text
    intent_body = intent.json()
    assert intent_body["object_key"].startswith("uploads/")

    app = client.app
    async with httpx.AsyncClient() as storage_client:
        uploaded = await storage_client.put(
            intent_body["upload_url"],
            content=b"\x89PNG fake-bytes",
            headers=intent_body["headers"],
        )
    assert uploaded.status_code in {200, 204}, uploaded.text

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
    assert fetched.json()["bucket"] == RUSTFS_BUCKET

    url = await client.get(
        f"/api/v1/admin/assets/{asset_id}/url",
        params={"expires_in_seconds": 120},
        headers=headers,
    )
    assert url.status_code == 200
    assert "X-Amz-Expires=120" in url.json()["url"]
    async with httpx.AsyncClient() as storage_client:
        downloaded = await storage_client.get(url.json()["url"])
    assert downloaded.status_code == 200
    assert downloaded.content == b"\x89PNG fake-bytes"

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


async def test_assets_list_is_paged_and_filterable(client: Any, admin_token: str) -> None:
    from inc.capabilities.assets.models import AssetMetadata, AssetObject

    services = client.app.state.services
    async with services.uow_factory() as uow:
        uow.session.add(
            AssetObject(
                provider_key="s3",
                bucket="site-assets",
                object_key="uploads/logo.svg",
                mime_type="image/svg+xml",
                byte_size=42,
                asset_metadata=AssetMetadata(values={"role": "logo"}),
                state="ready",
            )
        )
        await uow.commit()

    response = await client.get(
        "/api/v1/admin/assets",
        params={"page": 1, "size": 10, "search": "logo"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["object_key"] == "uploads/logo.svg"


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
