"""SMTP email adapter (NotificationProvider implementation).

Contract source: context/spec/adapters.md §3.1, context/spec/capabilities/notification.md §4.

Thin wrapper over aiosmtplib: owns connection settings, credentials,
timeout and error classification. Connection settings are filled through
the ``site_settings`` ``notification`` settings group
(``smtp_settings_from_group``). The adapter reads that group for each
delivery and builds a per-call ``SmtpSettings`` snapshot, so committed
settings changes apply to the next delivery without rebuilding the adapter.
SMTP has no native idempotency, so the stable delivery idempotency key is
passed through for provider-side deduplication where supported, and the
adapter never guesses outcomes on timeout (unknown).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiosmtplib

from inc.capabilities.notification.ports import (
    ProviderError,
    ProviderResult,
    RecipientTarget,
)
from inc.capabilities.settings import SettingsQueries
from inc.kernel.errors import ErrorCategory

_SMTP_TIMEOUT = 15.0

_DEFAULT_FROM_ADDRESS = "no-reply@aiya.local"


@dataclass(frozen=True, slots=True)
class SmtpSettings:
    host: str
    port: int = 25
    username: str | None = None
    password: str | None = None  # noqa: S105
    from_address: str = _DEFAULT_FROM_ADDRESS
    use_tls: bool = False
    starttls: bool = False
    timeout_seconds: float = _SMTP_TIMEOUT

    def __repr__(self) -> str:
        return (
            f"SmtpSettings(host={self.host!r}, port={self.port}, "
            f"username={self.username!r}, from_address={self.from_address!r}, "
            f"use_tls={self.use_tls}, starttls={self.starttls}, "
            f"timeout_seconds={self.timeout_seconds})"
        )


def smtp_settings_from_group(
    value: dict[str, Any], *, timeout_seconds: float = _SMTP_TIMEOUT
) -> SmtpSettings:
    """Build SmtpSettings from the site_settings ``notification`` group value.

    Missing/empty host means the channel is not configured; the current
    delivery is rejected rather than attempting a connection that cannot work.
    """

    host = value.get("smtp_host", "")
    if not host:
        raise ValueError(
            "notification settings group has no smtp_host; SMTP delivery cannot be sent"
        )
    return SmtpSettings(
        host=host,
        port=value.get("smtp_port", 25),
        username=value.get("smtp_username") or None,
        password=value.get("smtp_password") or None,
        from_address=value.get("smtp_from_address", _DEFAULT_FROM_ADDRESS),
        use_tls=_parse_bool(value.get("smtp_use_tls", False)),
        starttls=_parse_bool(value.get("smtp_starttls", False)),
        timeout_seconds=timeout_seconds,
    )


def _parse_bool(value: Any) -> bool:
    """Parse boolean-like config values without misreading 'false'/'0'."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class _AfterDataSentError(Exception):
    """Raised when the message may have been handed to the server."""


def _validate_header_value(value: str, label: str) -> str:
    """Reject CR/LF so a value cannot inject extra SMTP headers."""

    if "\r" in value or "\n" in value:
        raise ValueError(f"{label} must not contain CR/LF")
    return value


def _encode_header(value: str) -> str:
    """RFC 5322 header-safe subject: strip control chars, RFC 2047-encode
    any non-ASCII so the wire format stays 7-bit ASCII."""

    import base64

    value = "".join(ch for ch in value if ch not in ("\r", "\n"))
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return f"=?utf-8?B?{base64.b64encode(value.encode('utf-8')).decode('ascii')}?="
    return value


class SmtpEmailAdapter:
    """NotificationProvider over SMTP; key ``email.smtp``."""

    key = "email.smtp"

    def __init__(
        self, *, settings_queries: SettingsQueries, timeout_seconds: float = _SMTP_TIMEOUT
    ) -> None:
        self._settings_queries = settings_queries
        self._timeout_seconds = timeout_seconds

    async def _current_settings(self) -> SmtpSettings:
        group = await self._settings_queries.get_group("notification")
        return smtp_settings_from_group(group.values, timeout_seconds=self._timeout_seconds)

    async def send(
        self,
        *,
        target: RecipientTarget,
        subject: str,
        body: str,
        idempotency_key: str,
    ) -> ProviderResult:
        try:
            settings = await self._current_settings()
        except ValueError as exc:
            raise ProviderError(
                message="SMTP settings are invalid",
                category=ErrorCategory.VALIDATION,
                permanent=True,
            ) from exc
        from_address = _validate_header_value(settings.from_address, "from_address")
        to_address = _validate_header_value(target.address, "recipient address")
        message = (
            f"From: {from_address}\r\n"
            f"To: {to_address}\r\n"
            f"Subject: {_encode_header(subject)}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "MIME-Version: 1.0\r\n"
            f"Message-ID: <{_validate_header_value(idempotency_key, 'idempotency_key')}"
            "@aiya.local>\r\n"
            "\r\n"
            f"{body}"
        ).encode()
        try:
            result = await asyncio.wait_for(
                self._send_raw(settings, message, to_address),
                timeout=settings.timeout_seconds,
            )
            return ProviderResult(status="delivered", provider_ref=result)
        except TimeoutError:
            return ProviderResult(
                status="unknown",
                error_category="timeout",
                error_summary="SMTP send timed out; outcome unknown",
            )
        except _AfterDataSentError as exc:
            return ProviderResult(
                status="unknown",
                error_category="timeout",
                error_summary=f"SMTP failed after DATA was accepted: {exc}",
            )
        except aiosmtplib.SMTPRecipientsRefused as exc:
            raise ProviderError(
                message="SMTP recipient refused",
                category=ErrorCategory.VALIDATION,
                permanent=True,
            ) from exc
        except aiosmtplib.SMTPAuthenticationError as exc:
            raise ProviderError(
                message="SMTP authentication failed",
                category=ErrorCategory.VALIDATION,
                permanent=True,
            ) from exc
        except aiosmtplib.SMTPException as exc:
            raise ProviderError(
                message=f"SMTP failure: {type(exc).__name__}",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            ) from exc
        except OSError as exc:
            raise ProviderError(
                message="SMTP connection failed",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            ) from exc

    async def _send_raw(self, settings: SmtpSettings, message: bytes, to_address: str) -> str:
        client = aiosmtplib.SMTP(
            hostname=settings.host,
            port=settings.port,
            use_tls=settings.use_tls,
            start_tls=settings.starttls,
            timeout=settings.timeout_seconds,
        )
        async with client:
            if settings.username:
                await client.login(settings.username, settings.password or "")
            try:
                await client.sendmail(settings.from_address, [to_address], message)
            except aiosmtplib.SMTPRecipientsRefused:
                # Raised during the RCPT phase, before DATA is sent; propagate
                # so send() maps it to a permanent VALIDATION ProviderError.
                raise
            except (aiosmtplib.SMTPException, OSError) as exc:
                raise _AfterDataSentError(f"{type(exc).__name__} after DATA accepted") from exc
        return f"{settings.host}:{settings.port}"
