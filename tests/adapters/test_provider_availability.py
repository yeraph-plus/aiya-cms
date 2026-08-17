"""Settings-backed adapter availability and redaction contracts."""

from __future__ import annotations

from typing import Any

from inc.adapters.assets.s3 import S3ObjectStorage
from inc.adapters.notification.email_smtp import SmtpEmailAdapter
from inc.adapters.notification.smtp2go import Smtp2GoEmailAdapter


class _Group:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values


class _Settings:
    def __init__(self, values: dict[str, Any]) -> None:
        self._group = _Group(values)

    async def get_group(self, _group_key: str) -> _Group:
        return self._group


async def test_email_adapters_report_safe_unavailable_for_missing_settings() -> None:
    settings = _Settings({"smtp_password": "must-not-appear", "smtp2go_api_key": "secret"})
    smtp = SmtpEmailAdapter(settings_queries=settings)  # type: ignore[arg-type]
    smtp2go = Smtp2GoEmailAdapter(settings_queries=settings)  # type: ignore[arg-type]

    assert await smtp.check_availability() == (False, "notification.provider_unavailable")
    assert await smtp2go.check_availability() == (False, "notification.provider_unavailable")


async def test_s3_reports_safe_unavailable_and_public_content_url_is_stable() -> None:
    unavailable = S3ObjectStorage(settings_queries=_Settings({}))  # type: ignore[arg-type]
    assert await unavailable.check_availability() == (False, "assets.provider_unavailable")

    settings = _Settings(
        {
            "s3_endpoint_url": "https://s3.example.test",
            "s3_bucket": "system",
            "s3_avatar_bucket": "avatars",
            "s3_content_bucket": "content",
            "s3_public_base_url": "https://cdn.example.test/media",
            "s3_region": "cn-north-1",
            "s3_addressing_style": "path",
            "s3_access_key_id": "access-key",
            "s3_secret_access_key": "must-not-appear",
        }
    )
    storage = S3ObjectStorage(settings_queries=settings)  # type: ignore[arg-type]
    url = await storage.public_url(bucket="content", object_key="content/a image.webp")
    assert url == "https://cdn.example.test/media/content/content/a%20image.webp"
    assert "?" not in url and "must-not-appear" not in url
