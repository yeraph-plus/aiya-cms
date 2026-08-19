"""Small lazy HTTP boundary shared by archive adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import requests


@dataclass(frozen=True, slots=True)
class HttpJsonResult:
    status_code: int
    document: Any
    headers: dict[str, str]
    failure: str | None = None
    retry_after_seconds: int | None = None


def safe_secret(value: Any) -> str:
    getter = getattr(value, "get_secret_value", None)
    raw = getter() if callable(getter) else value
    return str(raw or "").strip()


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def parse_timeout(value: Any, default: float) -> float:
    try:
        timeout = float(value)
    except TypeError, ValueError:
        timeout = default
    return max(0.1, min(timeout, 60.0))


def safe_base_url(value: Any) -> str:
    normalized = str(value or "").strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return ""
    return normalized


def safe_browser_url(value: Any) -> str | None:
    normalized = str(value or "").strip()
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    secret_names = {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
    }
    if any(key.lower() in secret_names for key, _ in parse_qsl(parsed.query)):
        return None
    return normalized


def retry_after(headers: dict[str, str]) -> int | None:
    value = headers.get("retry-after") or headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0, min(int(value), 86_400))
    except ValueError:
        return None


async def request_json(
    request: Callable[..., Any] | None,
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
    json_body: dict[str, Any] | None = None,
) -> HttpJsonResult:
    """Call a synchronous requests-compatible function without network at import."""

    sender = request or requests.request
    try:
        response = await asyncio.to_thread(
            sender,
            method,
            url,
            headers=headers,
            json=json_body,
            timeout=timeout_seconds,
            allow_redirects=False,
        )
    except requests.Timeout, TimeoutError:
        return HttpJsonResult(status_code=0, document=None, headers={}, failure="timeout")
    except requests.RequestException:
        return HttpJsonResult(status_code=0, document=None, headers={}, failure="dependency")
    except Exception:
        # A mock or alternative HTTP client must not leak its exception text.
        return HttpJsonResult(status_code=0, document=None, headers={}, failure="dependency")

    status_code = int(getattr(response, "status_code", 0) or 0)
    raw_headers = getattr(response, "headers", {}) or {}
    response_headers = {str(key): str(value) for key, value in dict(raw_headers).items()}
    try:
        document = response.json()
    except ValueError, TypeError, AttributeError:
        document = None
    return HttpJsonResult(
        status_code=status_code,
        document=document,
        headers=response_headers,
        failure="protocol" if status_code == 200 and document is None else None,
        retry_after_seconds=retry_after(response_headers),
    )


def failure_code(result: HttpJsonResult) -> str:
    if result.failure == "timeout":
        return "timeout"
    if result.failure == "dependency":
        return "provider_unavailable"
    if result.status_code == 429:
        return "rate_limited"
    if isinstance(result.document, dict):
        provider_code = result.document.get("code")
        provider_status = str(result.document.get("status") or "").lower()
        if provider_code == 429 or "rate" in str(provider_code).lower():
            return "rate_limited"
        if provider_status in {"rate_limited", "rate-limit", "ratelimited"}:
            return "rate_limited"
    if result.status_code in {401, 403}:
        return "forbidden"
    if result.status_code == 404:
        return "not_found"
    if result.status_code in {408, 504}:
        return "timeout"
    if result.failure == "protocol" or not 200 <= result.status_code < 300:
        return "provider_unavailable"
    return "provider_unavailable"


def successful_json(result: HttpJsonResult) -> bool:
    if result.failure is not None or not 200 <= result.status_code < 300:
        return False
    if not isinstance(result.document, dict):
        return False
    code = result.document.get("code")
    if isinstance(code, int) and code not in {200, 0}:
        return False
    status = result.document.get("status")
    if status is not None and str(status).lower() not in {"ok", "success"}:
        return False
    return True


def document_data(document: Any) -> Any:
    if not isinstance(document, dict):
        return None
    value = document.get("data", document)
    return value
