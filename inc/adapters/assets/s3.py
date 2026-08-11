"""S3-compatible ObjectStorageProvider implementation.

The adapter reads the ``site_settings.object_storage`` group for every
provider operation. This keeps credential and endpoint changes effective for
the next upload, stat, URL resolution or delete without rebuilding the
application container.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from inc.capabilities.assets.ports import (
    ObjectStat,
    StorageError,
    UploadIntentCredentials,
    permanent_storage_error,
    storage_error,
)
from inc.capabilities.settings import SettingsQueries
from inc.kernel.time import SYSTEM_CLOCK, Clock

_SETTINGS_GROUP = "object_storage"
_MAX_PRESIGN_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class S3Settings:
    endpoint_url: str
    virtual_host_url: str
    bucket: str
    avatar_bucket: str
    region: str
    addressing_style: str
    access_key_id: str
    secret_access_key: str

    @classmethod
    def from_values(cls, values: dict[str, Any]) -> S3Settings:
        endpoint_url = _required_url(values.get("s3_endpoint_url"), "s3_endpoint_url")
        virtual_host_url = _optional_url(values.get("s3_virtual_host_url"), "s3_virtual_host_url")
        bucket = str(values.get("s3_bucket") or "").strip()
        avatar_bucket = str(values.get("s3_avatar_bucket") or f"{bucket}-avatars").strip()
        region = str(values.get("s3_region") or "").strip()
        addressing_style = str(values.get("s3_addressing_style") or "path").strip()
        access_key_id = _secret_value(values.get("s3_access_key_id"))
        secret_access_key = _secret_value(values.get("s3_secret_access_key"))
        if not bucket:
            raise _invalid_config("s3_bucket")
        if not avatar_bucket:
            raise _invalid_config("s3_avatar_bucket")
        if not region:
            raise _invalid_config("s3_region")
        if addressing_style not in {"path", "virtual"}:
            raise _invalid_config("s3_addressing_style")
        if not access_key_id or not secret_access_key:
            raise _invalid_config("s3 credentials")
        return cls(
            endpoint_url=endpoint_url,
            virtual_host_url=virtual_host_url,
            bucket=bucket,
            avatar_bucket=avatar_bucket,
            region=region,
            addressing_style=addressing_style,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )

    def __repr__(self) -> str:
        return (
            f"S3Settings(endpoint_url={self.endpoint_url!r}, "
            f"virtual_host_url={self.virtual_host_url!r}, bucket={self.bucket!r}, "
            f"avatar_bucket={self.avatar_bucket!r}, "
            f"region={self.region!r}, addressing_style={self.addressing_style!r})"
        )


class S3ObjectStorage:
    """S3-compatible object storage over boto3's synchronous client."""

    key = "s3"

    def __init__(self, *, settings_queries: SettingsQueries, clock: Clock = SYSTEM_CLOCK) -> None:
        self._settings_queries = settings_queries
        self._clock = clock

    async def _settings(self) -> S3Settings:
        group = await self._settings_queries.get_group(_SETTINGS_GROUP)
        try:
            return S3Settings.from_values(group.values)
        except ValueError as exc:
            raise permanent_storage_error(
                "assets.s3_invalid_config", "S3 object storage settings are invalid"
            ) from exc

    @staticmethod
    def _client(
        settings: S3Settings, *, bucket: str | None = None, for_presign: bool = False
    ) -> Any:
        import boto3  # type: ignore[import-untyped]
        from botocore.client import Config  # type: ignore[import-untyped]

        bucket = bucket or settings.bucket
        endpoint_url = settings.endpoint_url
        addressing_style = settings.addressing_style
        if for_presign and settings.virtual_host_url:
            endpoint_url = settings.virtual_host_url.replace("{bucket}", bucket)
            if "{bucket}" in settings.virtual_host_url:
                addressing_style = "virtual"
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": addressing_style},
            ),
        )

    @staticmethod
    def _bucket(settings: S3Settings, requested: str | None) -> str:
        if requested in (None, "", "system", settings.bucket):
            return settings.bucket
        if requested in ("avatar", settings.avatar_bucket):
            return settings.avatar_bucket
        raise _invalid_config("bucket")

    async def create_upload_intent(
        self,
        *,
        bucket: str | None = None,
        object_key: str,
        content_length_max: int,
        mime_types: tuple[str, ...],
        checksum_sha256: str | None,
        expires_at: datetime,
    ) -> UploadIntentCredentials:
        settings = await self._settings()
        target_bucket = self._bucket(settings, bucket)
        client = self._client(settings, bucket=target_bucket, for_presign=True)
        params: dict[str, Any] = {"Bucket": target_bucket, "Key": object_key}
        headers: dict[str, str] = {}
        if len(mime_types) == 1:
            params["ContentType"] = mime_types[0]
            headers["Content-Type"] = mime_types[0]
        if checksum_sha256 is not None:
            params["ChecksumSHA256"] = checksum_sha256
            headers["x-amz-checksum-sha256"] = checksum_sha256
        try:
            upload_url = await asyncio.to_thread(
                client.generate_presigned_url,
                "put_object",
                Params=params,
                ExpiresIn=_presign_seconds(expires_at, now=self._clock.utc_now()),
                HttpMethod="PUT",
            )
        except Exception as exc:  # noqa: BLE001 - SDK errors map to storage errors
            raise _map_error(exc, "create upload intent") from exc
        return UploadIntentCredentials(upload_url=upload_url, headers=headers)

    async def stat(self, *, bucket: str | None = None, object_key: str) -> ObjectStat:
        settings = await self._settings()
        target_bucket = self._bucket(settings, bucket)
        client = self._client(settings, bucket=target_bucket)
        try:
            result = await asyncio.to_thread(
                client.head_object,
                Bucket=target_bucket,
                Key=object_key,
            )
        except Exception as exc:  # noqa: BLE001 - SDK errors map to storage errors
            raise _map_error(exc, "stat object") from exc
        return ObjectStat(
            byte_size=int(result.get("ContentLength", 0)),
            mime_type=str(result.get("ContentType") or "application/octet-stream"),
            checksum_sha256=result.get("ChecksumSHA256"),
            bucket=target_bucket,
        )

    async def read_url(
        self, *, bucket: str | None = None, object_key: str, expires_in_seconds: int
    ) -> str:
        settings = await self._settings()
        target_bucket = self._bucket(settings, bucket)
        client = self._client(settings, bucket=target_bucket, for_presign=True)
        try:
            return await asyncio.to_thread(
                client.generate_presigned_url,
                "get_object",
                Params={"Bucket": target_bucket, "Key": object_key},
                ExpiresIn=expires_in_seconds,
                HttpMethod="GET",
            )
        except Exception as exc:  # noqa: BLE001 - SDK errors map to storage errors
            raise _map_error(exc, "create read URL") from exc

    async def delete(self, *, bucket: str | None = None, object_key: str) -> None:
        settings = await self._settings()
        target_bucket = self._bucket(settings, bucket)
        client = self._client(settings, bucket=target_bucket)
        try:
            await asyncio.to_thread(client.delete_object, Bucket=target_bucket, Key=object_key)
        except Exception as exc:  # noqa: BLE001 - SDK errors map to storage errors
            if _error_code(exc) in {"404", "NoSuchKey", "NoSuchObject", "NotFound"}:
                return
            raise _map_error(exc, "delete object") from exc


def _secret_value(value: Any) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    return str(getter() if getter is not None else value).strip()


def _required_url(value: Any, field: str) -> str:
    normalized = _optional_url(value, field)
    if not normalized:
        raise _invalid_config(field)
    return normalized


def _optional_url(value: Any, field: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise _invalid_config(field)
    return normalized


def _invalid_config(field: str) -> ValueError:
    return ValueError(f"invalid S3 setting: {field}")


def _presign_seconds(expires_at: datetime, *, now: datetime) -> int:
    effective = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at
    current = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    remaining = int((effective - current).total_seconds())
    return max(1, min(_MAX_PRESIGN_SECONDS, remaining))


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            return str(error.get("Code") or "")
    return type(exc).__name__


def _map_error(exc: Exception, operation: str) -> StorageError:
    code = _error_code(exc)
    if code in {"NoSuchKey", "NoSuchObject", "404", "NotFound"}:
        return permanent_storage_error("assets.object_missing", "object is missing")
    if code == "NoSuchBucket":
        return permanent_storage_error("assets.bucket_missing", "storage bucket is missing")
    if code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
        return permanent_storage_error("assets.provider_denied", "storage provider denied request")
    if code in {"NoCredentialsError", "PartialCredentialsError"}:
        return permanent_storage_error("assets.s3_invalid_config", "S3 credentials are invalid")
    return storage_error(f"S3 {operation} failed")
