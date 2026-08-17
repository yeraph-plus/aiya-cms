"""SMTP2GO REST API implementation of the notification email Port.

Contract source: context/spec/adapters.md section 3.1 and
context/spec/capabilities/notification.md section 4.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import formataddr
from typing import Any

import requests

from inc.capabilities.notification.ports import ProviderResult, RecipientTarget
from inc.capabilities.settings import SettingsQueries

SMTP2GO_ENDPOINTS = {
    "global": "https://api.smtp2go.com/v3/email/send",
    "us": "https://us-api.smtp2go.com/v3/email/send",
    "eu": "https://eu-api.smtp2go.com/v3/email/send",
}

_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 15.0
_DEFAULT_FROM_ADDRESS = "no-reply@aiya.local"


@dataclass(frozen=True, slots=True)
class Smtp2GoSettings:
    enabled: bool
    api_key: str | None
    endpoint: str
    from_name: str
    from_address: str
    connect_timeout_seconds: float = _CONNECT_TIMEOUT
    read_timeout_seconds: float = _READ_TIMEOUT

    def __repr__(self) -> str:
        return (
            f"Smtp2GoSettings(enabled={self.enabled}, api_key_configured="
            f"{bool(self.api_key)}, endpoint={self.endpoint!r}, "
            f"from_name={self.from_name!r}, from_address={self.from_address!r}, "
            f"connect_timeout_seconds={self.connect_timeout_seconds}, "
            f"read_timeout_seconds={self.read_timeout_seconds})"
        )


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _secret_value(value: Any) -> str | None:
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    raw = getter() if callable(getter) else value
    text = str(raw).strip()
    return text or None


def smtp2go_settings_from_group(
    value: dict[str, Any],
    *,
    connect_timeout_seconds: float = _CONNECT_TIMEOUT,
    read_timeout_seconds: float = _READ_TIMEOUT,
) -> Smtp2GoSettings:
    """Build an inert per-send settings snapshot from ``site_settings``."""

    region = str(value.get("smtp2go_region", "global") or "global").lower()
    return Smtp2GoSettings(
        enabled=(
            _parse_bool(value.get("email_enabled", False))
            and _parse_bool(value.get("smtp2go_enabled", False))
        ),
        api_key=_secret_value(value.get("smtp2go_api_key")),
        endpoint=SMTP2GO_ENDPOINTS.get(region, ""),
        from_name=str(value.get("default_from_name", "Aiya CMS") or ""),
        from_address=str(value.get("smtp_from_address", _DEFAULT_FROM_ADDRESS) or ""),
        connect_timeout_seconds=connect_timeout_seconds,
        read_timeout_seconds=read_timeout_seconds,
    )


def _safe_header(value: str, label: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError(f"{label} must not contain CR/LF")
    return value


class Smtp2GoEmailAdapter:
    """NotificationProvider over SMTP2GO's ``/v3/email/send`` endpoint."""

    key = "email.smtp2go"

    def __init__(
        self,
        *,
        settings_queries: SettingsQueries,
        post: Callable[..., Any] = requests.post,
        connect_timeout_seconds: float = _CONNECT_TIMEOUT,
        read_timeout_seconds: float = _READ_TIMEOUT,
    ) -> None:
        self._settings_queries = settings_queries
        self._post = post
        self._connect_timeout_seconds = connect_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds

    async def _current_settings(self) -> Smtp2GoSettings:
        group = await self._settings_queries.get_group("notification")
        return smtp2go_settings_from_group(
            group.values,
            connect_timeout_seconds=self._connect_timeout_seconds,
            read_timeout_seconds=self._read_timeout_seconds,
        )

    async def send(
        self,
        *,
        target: RecipientTarget,
        subject: str,
        body: str,
        idempotency_key: str,
    ) -> ProviderResult:
        settings = await self._current_settings()
        if not settings.enabled:
            return ProviderResult(
                status="unavailable",
                error_category="disabled",
                error_summary="SMTP2GO adapter is disabled",
            )
        if not settings.api_key or not settings.endpoint or not settings.from_address:
            return ProviderResult(
                status="unavailable",
                error_category="configuration",
                error_summary="SMTP2GO adapter is not fully configured",
            )

        sender = formataddr(
            (
                _safe_header(settings.from_name, "from_name"),
                _safe_header(settings.from_address, "from_address"),
            )
        )
        payload = {
            "api_key": settings.api_key,
            "sender": sender,
            "to": [_safe_header(target.address, "recipient address")],
            "subject": _safe_header(subject, "subject"),
            "text_body": body,
            "custom_headers": [
                {
                    "header": "X-Aiya-Idempotency-Key",
                    "value": _safe_header(idempotency_key, "idempotency_key"),
                }
            ],
        }
        try:
            response = await asyncio.to_thread(
                self._post,
                settings.endpoint,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Smtp2go-Api-Key": settings.api_key,
                },
                json=payload,
                timeout=(
                    settings.connect_timeout_seconds,
                    settings.read_timeout_seconds,
                ),
                allow_redirects=False,
            )
        except requests.ConnectTimeout:
            return ProviderResult(
                status="failed",
                error_category="transient",
                error_summary="SMTP2GO connection timed out before a response",
                fallback_allowed=True,
            )
        except requests.ReadTimeout:
            return ProviderResult(
                status="unknown",
                error_category="timeout",
                error_summary="SMTP2GO response timed out; outcome unknown",
            )
        except requests.RequestException as exc:
            return ProviderResult(
                status="unknown",
                error_category="dependency",
                error_summary=f"SMTP2GO request ended ambiguously ({type(exc).__name__})",
            )

        if response.status_code == 429:
            return ProviderResult(
                status="failed",
                error_category="rate_limited",
                error_summary="SMTP2GO rate limit rejected the request",
                fallback_allowed=True,
            )
        if response.status_code == 400:
            return ProviderResult(
                status="failed",
                error_category="permanent",
                error_summary="SMTP2GO rejected the request",
            )
        if response.status_code != 200:
            return ProviderResult(
                status="unknown",
                error_category="dependency",
                error_summary=f"SMTP2GO returned HTTP {response.status_code}; outcome unknown",
            )

        try:
            document = response.json()
            email_response = document["email_response"]
            succeeded = int(email_response.get("succeeded", 0))
            failed = int(email_response.get("failed", 0))
        except (KeyError, TypeError, ValueError, AttributeError) as _exc:
            del _exc
            return ProviderResult(
                status="unknown",
                error_category="protocol",
                error_summary="SMTP2GO returned an invalid success response",
            )

        if succeeded == 1 and failed == 0:
            provider_ref = email_response.get("email_id")
            return ProviderResult(
                status="delivered",
                provider_ref=str(provider_ref) if provider_ref else None,
            )
        if failed >= 1 and succeeded == 0:
            return ProviderResult(
                status="failed",
                error_category="permanent",
                error_summary="SMTP2GO rejected the recipient",
            )
        return ProviderResult(
            status="unknown",
            error_category="protocol",
            error_summary="SMTP2GO returned an ambiguous delivery count",
        )
