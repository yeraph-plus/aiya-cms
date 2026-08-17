"""S3 adapter unit tests that do not require an object storage service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from inc.adapters.assets.s3 import S3ObjectStorage
from inc.capabilities.assets.ports import StorageError


class _SettingsReader:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.calls = 0

    async def get_group(self, group_key: str) -> Any:
        assert group_key == "object_storage"
        self.calls += 1
        return type("SettingGroup", (), {"values": dict(self.values)})()


def _values() -> dict[str, Any]:
    return {
        "s3_endpoint_url": "http://127.0.0.1:9000",
        "s3_virtual_host_url": "",
        "s3_bucket": "aiya-assets",
        "s3_region": "us-east-1",
        "s3_addressing_style": "path",
        "s3_access_key_id": "rustfsadmin",
        "s3_secret_access_key": "rustfsadmin",
    }


async def test_presigned_urls_use_current_settings() -> None:
    reader = _SettingsReader(_values())
    adapter = S3ObjectStorage(settings_queries=reader)
    expiry = datetime.now(UTC) + timedelta(hours=1)

    upload = await adapter.create_upload_intent(
        object_key="uploads/test/object.txt",
        content_length_max=100,
        mime_types=("text/plain",),
        checksum_sha256=None,
        expires_at=expiry,
    )
    read_url = await adapter.read_url(object_key="uploads/test/object.txt", expires_in_seconds=120)

    assert upload.upload_url.startswith("http://127.0.0.1:9000/aiya-assets/")
    assert "X-Amz-Signature=" in upload.upload_url
    assert upload.headers == {"Content-Type": "text/plain"}
    assert read_url.startswith("http://127.0.0.1:9000/aiya-assets/")
    assert "X-Amz-Expires=120" in read_url
    reader.values["s3_virtual_host_url"] = "http://storage.example:9000"
    changed_read_url = await adapter.read_url(
        object_key="uploads/test/object.txt", expires_in_seconds=120
    )
    assert changed_read_url.startswith("http://storage.example:9000/aiya-assets/")
    assert reader.calls == 3


async def test_invalid_settings_are_mapped_without_leaking_values() -> None:
    reader = _SettingsReader({"s3_secret_access_key": "do-not-leak"})
    adapter = S3ObjectStorage(settings_queries=reader)

    with pytest.raises(StorageError) as excinfo:
        await adapter.read_url(object_key="missing", expires_in_seconds=1)

    assert excinfo.value.code == "assets.provider_unavailable"
    assert "do-not-leak" not in str(excinfo.value)
