"""Executable smoke coverage for the ASGI scaffold."""

import httpx
import pytest

from inc.api.app import create_app
from inc.kernel.config import Settings


@pytest.mark.asyncio
async def test_health_endpoint_reports_application_status() -> None:
    application = create_app(Settings(_env_file=None, env="test"))
    transport = httpx.ASGITransport(app=application)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "test"}
