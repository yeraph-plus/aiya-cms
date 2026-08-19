"""HTTP-mock contracts for OpenList and Gofile archive adapters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from inc.adapters.archive.gofile import GofileArchiveProvider, GofileSettings
from inc.adapters.archive.openlist import OpenListArchiveProvider, OpenListSettings
from inc.capabilities.archive.models import ArchiveExternalLocator
from inc.capabilities.archive.ports import ArchiveDeliveryRequest


class _Response:
    def __init__(
        self, status_code: int, payload: object, headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> object:
        return self._payload


def _request_response(response: _Response, calls: list[dict[str, Any]]):
    def request(method: str, url: str, **kwargs: Any) -> _Response:
        calls.append({"method": method, "url": url, **kwargs})
        return response

    return request


async def test_adapters_are_inert_until_an_explicit_provider_call() -> None:
    calls: list[dict[str, Any]] = []
    openlist = OpenListArchiveProvider(
        settings=OpenListSettings(base_url="https://openlist.example.test", token="must-not-leak"),
        request=_request_response(_Response(200, {}), calls),
    )
    gofile = GofileArchiveProvider(
        settings=GofileSettings(api_token="must-not-leak"),
        request=_request_response(_Response(200, {}), calls),
    )
    assert calls == []
    assert (await openlist.check_availability()).available
    assert (await gofile.check_availability()).available
    assert calls == []
    assert "must-not-leak" not in repr(openlist._settings)
    assert "must-not-leak" not in repr(gofile._settings)


async def test_openlist_stat_and_header_only_delivery_are_typed_and_redacted() -> None:
    calls: list[dict[str, Any]] = []
    responses = [
        _Response(
            200,
            {"code": 200, "data": {"name": "part.zip", "size": 12, "is_dir": False}},
        ),
        _Response(
            200,
            {
                "code": 200,
                "data": {
                    "name": "part.zip",
                    "size": 12,
                    "raw_url": "https://download.example.test/part.zip",
                    "headers": {"Authorization": "provider-secret"},
                },
            },
        ),
    ]

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        calls.append({"method": method, "url": url, **kwargs})
        return responses.pop(0)

    provider = OpenListArchiveProvider(
        settings=OpenListSettings(
            base_url="https://openlist.example.test", token="provider-secret"
        ),
        request=request,
    )
    locator = ArchiveExternalLocator(value="/downloads/part.zip")
    fact = await provider.stat(locator)
    assert fact.available and fact.size_bytes == 12
    delivery = await provider.create_delivery(
        ArchiveDeliveryRequest(
            locator=locator,
            item_ref="item-1",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    assert delivery.status == "proxy_required"
    assert delivery.redirect_url is None
    assert "provider-secret" not in str(delivery.model_dump())
    assert calls[0]["headers"]["Authorization"] == "provider-secret"


async def test_429_and_timeout_become_safe_typed_results() -> None:
    rate_limited = OpenListArchiveProvider(
        settings=OpenListSettings(base_url="https://openlist.example.test", token="secret"),
        request=_request_response(
            _Response(429, {"message": "secret provider payload"}, {"Retry-After": "7"}), []
        ),
    )
    result = await rate_limited.create_delivery(
        ArchiveDeliveryRequest(
            locator=ArchiveExternalLocator(value="/file"),
            item_ref="item-1",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    assert result.status == "unavailable"
    assert result.reason_code == "rate_limited"
    assert result.retry_after_seconds == 7
    assert "secret provider payload" not in str(result.model_dump())

    def timeout(*_: Any, **__: Any) -> _Response:
        raise requests.Timeout("token=secret")

    timed_out = GofileArchiveProvider(
        settings=GofileSettings(api_token="secret"),
        request=timeout,
    )
    result = await timed_out.stat(ArchiveExternalLocator(value="content-id"))
    assert result.status == "unavailable"
    assert result.reason_code == "timeout"
    assert "secret" not in str(result.model_dump())


async def test_gofile_returns_only_expiring_browser_safe_direct_links() -> None:
    calls: list[dict[str, Any]] = []
    provider = GofileArchiveProvider(
        settings=GofileSettings(api_token="provider-secret"),
        request=_request_response(
            _Response(
                200,
                {
                    "status": "ok",
                    "data": {
                        "name": "part.zip",
                        "type": "file",
                        "size": 99,
                        "link": "https://download.example.test/file?expires=123",
                    },
                },
            ),
            calls,
        ),
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=2)
    result = await provider.create_delivery(
        ArchiveDeliveryRequest(
            locator=ArchiveExternalLocator(value="content-id"),
            item_ref="item-1",
            expires_at=expires_at,
        )
    )
    assert result.status == "redirect"
    assert result.redirect_url == "https://download.example.test/file?expires=123"
    assert result.expires_at == expires_at
    assert "provider-secret" not in str(result.model_dump())
    assert calls[0]["headers"]["Authorization"] == "Bearer provider-secret"
