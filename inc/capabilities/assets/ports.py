"""Assets provider Port.

Contract source: context/spec/capabilities/assets.md §4.

The assets capability declares its own ObjectStorageProvider; adapters own
SDK clients, credentials, timeouts, retries and error mapping. Credentials,
signed URLs and raw SDK errors never enter settings, the database or logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from inc.kernel.errors import ErrorCategory, KernelError


class StorageError(KernelError):
    """Provider failure mapped through the kernel category/retry mapping."""


def storage_error(message: str) -> StorageError:
    """Transient provider failure (dependency unavailable)."""

    return StorageError(
        code="assets.provider_unavailable",
        category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        message=message,
    )


def permanent_storage_error(code: str, message: str) -> StorageError:
    """Permanent provider outcome (missing object, bad checksum, denied)."""

    return StorageError(code=code, category=ErrorCategory.VALIDATION, message=message)


@dataclass(frozen=True, slots=True)
class UploadIntentCredentials:
    """Short-lived upload credentials; never persisted."""

    upload_url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ObjectStat:
    byte_size: int
    mime_type: str
    checksum_sha256: str | None = None
    bucket: str | None = None


@runtime_checkable
class ObjectStorageProvider(Protocol):
    """External object storage adapter contract."""

    key: str

    async def check_availability(self) -> tuple[bool, str | None]: ...

    async def create_upload_intent(
        self,
        *,
        bucket: str | None,
        object_key: str,
        content_length_max: int,
        mime_types: tuple[str, ...],
        checksum_sha256: str | None,
        expires_at: datetime,
    ) -> UploadIntentCredentials: ...

    async def stat(self, *, bucket: str | None, object_key: str) -> ObjectStat: ...

    async def read_url(
        self, *, bucket: str | None, object_key: str, expires_in_seconds: int
    ) -> str: ...

    async def read_bytes(self, *, bucket: str | None, object_key: str) -> bytes: ...

    async def put_bytes(
        self, *, bucket: str | None, object_key: str, body: bytes, mime_type: str
    ) -> ObjectStat: ...

    async def public_url(self, *, bucket: str | None, object_key: str) -> str: ...

    async def delete(self, *, bucket: str | None, object_key: str) -> None:
        """Idempotent delete: deleting a missing object must succeed.

        The delete workflow retries its step after provider timeouts, so
        adapters must treat "object already gone" as success (like S3) and
        never surface a raw 404.
        """
