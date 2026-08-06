"""Health endpoints.

Contract source: context/spec/http-openapi.md §2.

``/healthz`` is process liveness without dependencies; ``/api/v1/health``
reports manifest readiness.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict


class HealthDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    manifest: str
    capabilities: list[str] = []
    routers: list[str] = []


def build_router(
    *, manifest_name: str, capabilities: tuple[str, ...], routers: tuple[str, ...]
) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/api/v1/health", response_model=HealthDTO)
    async def health() -> HealthDTO:
        return HealthDTO(
            status="ok",
            manifest=manifest_name,
            capabilities=sorted(capabilities),
            routers=sorted(routers),
        )

    return router
