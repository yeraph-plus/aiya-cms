"""Thin Gofile REST adapter for the archive delivery Port."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

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
_DEFAULT_BASE_URL = "https://api.gofile.io"
_CONTRACT_VERSION = "gofile.v1"


@dataclass(frozen=True, slots=True)
class GofileSettings:
    base_url: str = _DEFAULT_BASE_URL
    api_token: str = ""
    allow_direct_link: bool = True
    timeout_seconds: float = _DEFAULT_TIMEOUT

    @classmethod
    def from_values(cls, values: dict[str, Any]) -> GofileSettings:
        configured_base = values.get(
            "archive_gofile_base_url", values.get("gofile_base_url", values.get("base_url"))
        )
        return cls(
            base_url=safe_base_url(configured_base or _DEFAULT_BASE_URL),
            api_token=safe_secret(
                values.get(
                    "archive_gofile_api_token",
                    values.get("gofile_api_token", values.get("api_token", values.get("token"))),
                )
            ),
            allow_direct_link=parse_bool(
                values.get(
                    "archive_gofile_allow_direct_link",
                    values.get("gofile_allow_direct_link", values.get("allow_direct_link", True)),
                )
            ),
            timeout_seconds=parse_timeout(
                values.get(
                    "archive_gofile_timeout_seconds",
                    values.get("gofile_timeout_seconds", values.get("timeout_seconds")),
                ),
                _DEFAULT_TIMEOUT,
            ),
        )

    def __repr__(self) -> str:
        return (
            f"GofileSettings(base_url={self.base_url!r}, "
            f"api_token_configured={bool(self.api_token)}, "
            f"allow_direct_link={self.allow_direct_link}, timeout_seconds={self.timeout_seconds})"
        )


class GofileArchiveProvider:
    key = "archive.gofile"
    contract_version = _CONTRACT_VERSION

    def __init__(
        self,
        *,
        settings_queries: Any | None = None,
        settings: GofileSettings | None = None,
        request: Callable[..., Any] | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._settings_queries = settings_queries
        self._settings = settings
        self._request = request
        self._timeout_seconds = timeout_seconds

    async def _current_settings(self, snapshot: ArchiveSettingsSnapshot | None) -> GofileSettings:
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
        parsed = GofileSettings.from_values(dict(values))
        return GofileSettings(
            base_url=parsed.base_url,
            api_token=parsed.api_token,
            allow_direct_link=parsed.allow_direct_link,
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
        if not settings.base_url or not settings.api_token:
            return ArchiveAvailability(
                available=False,
                reason_code="archive.provider_unavailable",
                contract_version=self.contract_version,
            )
        return ArchiveAvailability(available=True, contract_version=self.contract_version)

    def _headers(self, settings: GofileSettings) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {settings.api_token}",
            "User-Agent": "AIYA-CMS-Archive/1",
        }

    async def _get(self, settings: GofileSettings, content_id: str) -> Any:
        return await request_json(
            self._request,
            method="GET",
            url=f"{settings.base_url}/contents/{quote(content_id, safe='')}",
            headers=self._headers(settings),
            timeout_seconds=settings.timeout_seconds,
        )

    @staticmethod
    def _content_data(result: Any) -> dict[str, Any] | None:
        data = document_data(result.document)
        return data if isinstance(data, dict) else None

    async def stat(
        self,
        external_locator: ArchiveExternalLocator,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderFileFact:
        settings = await self._current_settings(settings_snapshot)
        if not settings.base_url or not settings.api_token:
            return ProviderFileFact(status="unavailable", reason_code="provider_unavailable")
        result = await self._get(settings, external_locator.value)
        if not successful_json(result):
            return ProviderFileFact(
                status="unavailable",
                reason_code=failure_code(result),
                retry_after_seconds=result.retry_after_seconds,
            )
        data = self._content_data(result)
        file_data = _first_file(data)
        if file_data is None:
            return ProviderFileFact(status="unavailable", reason_code="not_file")
        name = str(file_data.get("name") or "").strip()
        try:
            size = int(file_data.get("size", 0))
        except TypeError, ValueError:
            size = 0
        if not name or size <= 0:
            return ProviderFileFact(status="unavailable", reason_code="provider_unavailable")
        checksum = file_data.get("md5") or file_data.get("sha256")
        algorithm = (
            "md5" if file_data.get("md5") else ("sha256" if file_data.get("sha256") else None)
        )
        return ProviderFileFact(
            display_name=name,
            size_bytes=size,
            checksum_algorithm=algorithm,
            checksum_value=str(checksum) if checksum else None,
            provider_fact_version=self.contract_version,
        )

    async def create_delivery(
        self,
        request: ArchiveDeliveryRequest,
        settings_snapshot: ArchiveSettingsSnapshot | None = None,
    ) -> ProviderDelivery:
        settings = await self._current_settings(settings_snapshot)
        if not settings.base_url or not settings.api_token:
            return ProviderDelivery(status="unavailable", reason_code="provider_unavailable")
        result = await self._get(settings, request.locator.value)
        if not successful_json(result):
            return ProviderDelivery(
                status="unavailable",
                reason_code=failure_code(result),
                retry_after_seconds=result.retry_after_seconds,
            )
        data = self._content_data(result)
        file_data = _first_file(data)
        if file_data is None:
            return ProviderDelivery(status="unavailable", reason_code="not_file")
        if file_data.get("headers") or file_data.get("header"):
            return ProviderDelivery(
                status="proxy_required",
                provider_delivery_ref=_opaque_ref(file_data),
                reason_code="provider_secret_header_required",
                expires_at=request.expires_at,
            )
        if not settings.allow_direct_link:
            return ProviderDelivery(
                status="proxy_required",
                provider_delivery_ref=_opaque_ref(file_data),
                reason_code="proxy_required_by_policy",
                expires_at=request.expires_at,
            )
        redirect_url = safe_browser_url(
            file_data.get("link") or file_data.get("directLink") or file_data.get("direct_link")
        )
        if redirect_url is None:
            return ProviderDelivery(
                status="proxy_required",
                provider_delivery_ref=_opaque_ref(file_data),
                reason_code="direct_link_unavailable",
                expires_at=request.expires_at,
            )
        # The caller supplies the bounded grant window; the result is never
        # reusable after that timestamp even if the provider omits metadata.
        return ProviderDelivery(
            status="redirect",
            provider_delivery_ref=_opaque_ref(file_data),
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
        del external_locator, settings_snapshot
        return ()


def _first_file(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    if str(data.get("type") or "").lower() in {"file", "document"} or data.get("link"):
        return data
    children = data.get("children")
    values: Iterable[Any]
    if isinstance(children, dict):
        values = children.values()
    elif isinstance(children, list):
        values = children
    else:
        values = ()
    for child in values:
        if isinstance(child, dict) and not child.get("children"):
            return child
    return None


def _opaque_ref(data: dict[str, Any]) -> str | None:
    for key in ("id", "contentId", "content_id", "provider_ref"):
        value = data.get(key)
        if isinstance(value, (str, int)) and str(value) and "://" not in str(value):
            return str(value)
    return None


GofileProvider = GofileArchiveProvider
GofileAdapter = GofileArchiveProvider
