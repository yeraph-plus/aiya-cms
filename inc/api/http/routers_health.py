"""Health endpoints.

Contract source: context/spec/http-openapi.md §2.

``/healthz`` is process liveness without dependencies; ``/api/v1/health``
reports manifest readiness from the composition root's dependency probes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

ReadinessProbe = Callable[[], Awaitable[bool]]


class HealthDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    manifest: str
    capabilities: list[str] = []
    routers: list[str] = []


def build_router(
    *,
    manifest_name: str,
    capabilities: tuple[str, ...],
    routers: tuple[str, ...],
    readiness: ReadinessProbe | None = None,
) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/api/v1/health", response_model=HealthDTO)
    async def health() -> HealthDTO:
        ready = True
        if readiness is not None:
            try:
                ready = await readiness()
            except Exception:  # noqa: BLE001 - any probe failure means not ready
                ready = False
        return HealthDTO(
            status="ok" if ready else "degraded",
            manifest=manifest_name,
            capabilities=sorted(capabilities),
            routers=sorted(routers),
        )

    return router
