"""SMTP email adapter (NotificationProvider implementation).

Contract source: context/spec/capabilities/notification.md §4.

Thin wrapper over aiosmtplib: owns connection settings, credentials,
timeout and error classification. SMTP has no native idempotency, so the
stable delivery idempotency key is passed through for provider-side
deduplication where supported, and the adapter never guesses outcomes on
timeout (unknown).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiosmtplib

from inc.capabilities.notification.ports import (
    ProviderError,
    ProviderResult,
    RecipientTarget,
)
from inc.kernel.errors import ErrorCategory

_SMTP_TIMEOUT = 15.0


@dataclass(frozen=True, slots=True)
class SmtpSettings:
    host: str
    port: int = 25
    username: str | None = None
    password: str | None = None
    from_address: str = "no-reply@aiya.local"
    use_tls: bool = False
    starttls: bool = False
    timeout_seconds: float = _SMTP_TIMEOUT


class SmtpEmailAdapter:
    """NotificationProvider over SMTP; key ``email.smtp``."""

    key = "email.smtp"

    def __init__(self, *, settings: SmtpSettings) -> None:
        self._settings = settings

    async def send(
        self,
        *,
        target: RecipientTarget,
        subject: str,
        body: str,
        idempotency_key: str,
    ) -> ProviderResult:
        message = (
            f"From: {self._settings.from_address}\r\n"
            f"To: {target.address}\r\n"
            f"Subject: {subject}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "MIME-Version: 1.0\r\n"
            f"Message-ID: <{idempotency_key}@aiya.local>\r\n"
            "\r\n"
            f"{body}"
        ).encode()
        try:
            result = await asyncio.wait_for(
                self._send_raw(message, target.address),
                timeout=self._settings.timeout_seconds,
            )
            return ProviderResult(status="delivered", provider_ref=result)
        except TimeoutError:
            return ProviderResult(
                status="unknown",
                error_category="timeout",
                error_summary="SMTP send timed out; outcome unknown",
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

    async def _send_raw(self, message: bytes, to_address: str) -> str:
        settings = self._settings
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
            await client.sendmail(settings.from_address, [to_address], message)
        return f"{settings.host}:{settings.port}"
