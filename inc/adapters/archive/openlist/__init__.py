"""Thin OpenList REST adapter for the archive delivery Port."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from inc.adapters.archive._http import (
    document_data,
    failure_code,
    parse_bool,
    parse_timeout,
    request_json,
    safe_base_url,
    safe_browser_url,
    safe_secret,
    successful_json,
)
from inc.capabilities.archive.ports import (
    ArchiveAvailability,
    ArchiveDeliveryRequest,
    ArchiveExternalLocator,
    ArchiveSettingsSnapshot,
    ProviderChild,
    ProviderDelivery,
    ProviderFileFact,
    ProviderOperationResult,
)

_DEFAULT_TIMEOUT = 10.0
_CONTRACT_VERSION = "openlist.v1"


@dataclass(frozen=True, slots=True)
class OpenListSettings:
    base_url: str
    token: str
    allow_proxy: bool = False
    timeout_seconds: float = _DEFAULT_TIMEOUT

    @classmethod
    def from_values(cls, values: dict[str, Any]) -> OpenListSettings:
        return cls(
            base_url=safe_base_url(
                values.get(
                    "archive_openlist_base_url",
                    values.get("openlist_base_url", values.get("base_url")),
                )
            ),
            token=safe_secret(
                values.get(
                    "archive_openlist_token", values.get("openlist_token", values.get("token"))
                )
            ),
            allow_proxy=parse_bool(
                values.get(
                    "archive_openlist_allow_proxy",
                    values.get("openlist_allow_proxy", values.get("allow_proxy", False)),
                )
            ),
            timeout_seconds=parse_timeout(
                values.get(
                    "archive_openlist_timeout_seconds",
                    values.get("openlist_timeout_seconds", values.get("timeout_seconds")),
                ),
                _DEFAULT_TIMEOUT,
            ),
        )

    def __repr__(self) -> str:
        return (
            f"OpenListSettings(base_url={self.base_url!r}, token_configured={bool(self.token)}, "
            f"allow_proxy={self.allow_proxy}, timeout_seconds={self.timeout_seconds})"
        )


class OpenListArchiveProvider:
    key = "archive.openlist"
    contract_version = _CONTRACT_VERSION

    def __init__(
        self,
        *,
        settings_queries: Any | None = None,
        settings: OpenListSettings | None = None,
        request: Callable[..., Any] | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._settings_queries = settings_queries
        self._settings = settings
        self._request = request
        self._timeout_seconds = timeout_seconds

    async def _current_settings(self, snapshot: ArchiveSettingsSnapshot | None) -> OpenListSettings:
        if isinstance(snapshot, Mapping) and snapshot:
            values = dict(snapshot)
        elif snapshot is not None and snapshot.values:
            values = snapshot.values
        elif self._settings_queries is not None:
            group = await self._settings_queries.get_group("archive")
            values = group.values
        elif self._settings is not None:
            return self._settings
        else:
            values = {}
        parsed = OpenListSettings.from_values(dict(values))
        return OpenListSettings(
            base_url=parsed.base_url,
            token=parsed.token,
            allow_proxy=parsed.allow_proxy,
            timeout_seconds=min(parsed.timeout_seconds, self._timeout_seconds),
        )

    async def check_availability(
        self, settings_snapshot: ArchiveSettingsSnapshot | None = None
    ) -> ArchiveAvailability:
        try:
            settings = await self._current_settings(settings_snapshot)
        except Exception:
            return ArchiveAvailability(
                available=False,
                reason_code="archive.provider_unavailable",
                contract_version=self.contract_version,
            )
        if not settings.base_url or not settings.token:
            return ArchiveAvailability(
                available=False,
                reason_code="archive.provider_unavailable",
                contract_version=self.contract_version,
            )
        return ArchiveAvailability(available=True, contract_version=self.contract_version)

    def _headers(self, settings: OpenListSettings) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": settings.token,
            "User-Agent": "AIYA-CMS-Archive/1",
        }

    async def _post(self, settings: OpenListSettings, path: str, payload: dict[str, Any]) -> Any:
        return await request_json(
            self._request,
            method="POST",
            url=settings.base_url + path,
            headers=self._headers(settings),
            timeout_seconds=settings.timeout_seconds,
            json_body=payload,
        )

    @staticmethod
    def _payload_data(result: Any) -> dict[str, Any] | None:
        data = document_data(result.document)
        return data if isinstance(data, dict) else None

    async def stat(
        self,
        external_locator: ArchiveExternalLocator,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderFileFact:
        settings = await self._current_settings(settings_snapshot)
        if not settings.base_url or not settings.token:
            return ProviderFileFact(status="unavailable", reason_code="provider_unavailable")
        result = await self._post(
            settings,
            "/api/fs/get",
            {
                "path": external_locator.value,
                "password": "",
                "page": 1,
                "per_page": 0,
                "refresh": False,
            },
        )
        if not successful_json(result):
            return ProviderFileFact(
                status="unavailable",
                reason_code=failure_code(result),
                retry_after_seconds=result.retry_after_seconds,
            )
        data = self._payload_data(result)
        if data is None:
            return ProviderFileFact(status="unavailable", reason_code="provider_unavailable")
        is_directory = bool(data.get("is_dir", False)) or data.get("type") in {
            1,
            "1",
            "folder",
            "directory",
        }
        if is_directory:
            return ProviderFileFact(status="unavailable", reason_code="not_file")
        try:
            size = int(data.get("size", 0))
        except TypeError, ValueError:
            size = 0
        name = str(data.get("name") or "").strip()
        if size <= 0 or not name:
            return ProviderFileFact(status="unavailable", reason_code="provider_unavailable")
        checksum_algorithm, checksum_value = _checksum(data)
        return ProviderFileFact(
            display_name=name,
            size_bytes=size,
            checksum_algorithm=checksum_algorithm,
            checksum_value=checksum_value,
            provider_fact_version=self.contract_version,
        )

    async def create_delivery(
        self,
        request: ArchiveDeliveryRequest,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderDelivery:
        settings = await self._current_settings(settings_snapshot)
        if not settings.base_url or not settings.token:
            return ProviderDelivery(status="unavailable", reason_code="provider_unavailable")
        result = await self._post(
            settings,
            "/api/fs/get",
            {
                "path": request.locator.value,
                "password": "",
                "page": 1,
                "per_page": 0,
                "refresh": True,
            },
        )
        if not successful_json(result):
            return ProviderDelivery(
                status="unavailable",
                reason_code=failure_code(result),
                retry_after_seconds=result.retry_after_seconds,
            )
        data = self._payload_data(result)
        if data is None:
            return ProviderDelivery(status="unavailable", reason_code="provider_unavailable")
        required_headers = data.get("headers", data.get("header"))
        if required_headers:
            # A service-side proxy is required; never expose these headers.
            return ProviderDelivery(
                status="proxy_required",
                provider_delivery_ref=_opaque_ref(data),
                reason_code="provider_secret_header_required",
                expires_at=request.expires_at,
            )
        candidate = (
            data.get("raw_url") or data.get("download_url") or data.get("url") or data.get("link")
        )
        redirect_url = safe_browser_url(candidate)
        if redirect_url is None:
            return ProviderDelivery(
                status="unavailable",
                provider_delivery_ref=_opaque_ref(data),
                reason_code="delivery_not_browser_safe",
            )
        return ProviderDelivery(
            status="redirect",
            provider_delivery_ref=_opaque_ref(data),
            redirect_url=redirect_url,
            expires_at=request.expires_at,
        )

    async def refresh_delivery(
        self,
        provider_delivery_ref: str,
        request: ArchiveDeliveryRequest,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderDelivery:
        del provider_delivery_ref
        return await self.create_delivery(request, settings_snapshot)

    async def revoke_delivery(
        self,
        provider_delivery_ref: str,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderOperationResult:
        del provider_delivery_ref, settings_snapshot
        return ProviderOperationResult(status="unsupported", reason_code="not_supported")

    async def list_children(
        self,
        external_locator: ArchiveExternalLocator,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> tuple[ProviderChild, ...]:
        settings = await self._current_settings(settings_snapshot)
        if not settings.base_url or not settings.token:
            return ()
        result = await self._post(
            settings,
            "/api/fs/list",
            {
                "path": external_locator.value,
                "password": "",
                "page": 1,
                "per_page": 0,
                "refresh": False,
            },
        )
        if not successful_json(result):
            return ()
        data = self._payload_data(result)
        if not isinstance(data, dict):
            return ()
        content = data.get("content")
        if not isinstance(content, list):
            return ()
        children: list[ProviderChild] = []
        for value in content:
            if not isinstance(value, dict):
                continue
            name = str(value.get("name") or "").strip()
            if not name:
                continue
            child_value = f"{external_locator.value.rstrip('/')}/{name}"
            try:
                child_locator = ArchiveExternalLocator(value=child_value)
                size = int(value.get("size", 0)) or None
            except TypeError, ValueError:
                continue
            children.append(
                ProviderChild(
                    locator=child_locator,
                    display_name=name,
                    size_bytes=size if size and size > 0 else None,
                    is_directory=bool(value.get("is_dir", False)),
                )
            )
        return tuple(children)


def _checksum(data: dict[str, Any]) -> tuple[str | None, str | None]:
    value = data.get("hash")
    algorithm = "hash" if value else None
    info = data.get("hash_info")
    if isinstance(info, dict):
        for key in ("sha256", "md5", "hash"):
            candidate = info.get(key)
            if candidate:
                return key, str(candidate)
    return algorithm, str(value) if value else None


def _opaque_ref(data: dict[str, Any]) -> str | None:
    for key in ("id", "file_id", "provider_ref"):
        value = data.get(key)
        if isinstance(value, (str, int)) and str(value) and "://" not in str(value):
            return str(value)
    return None


OpenListProvider = OpenListArchiveProvider
OpenListAdapter = OpenListArchiveProvider
