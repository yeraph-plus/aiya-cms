"""Administrator-only projection of the comments capability."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from inc.api.container import Services
from inc.api.http.context import RequireCapability
from inc.api.http.routers_comments import build_router as build_comments_router

REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "comments.read",
    "comments.moderate",
    "comments.delete",
)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    source = build_comments_router(services, require_capability, require_authenticated)
    router = APIRouter()
    for route in source.routes:
        if getattr(route, "path", "").startswith("/api/v1/admin/"):
            router.routes.append(route)
    return router
