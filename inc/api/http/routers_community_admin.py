"""Administrator-only projection of the combined community router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from inc.api.container import Services
from inc.api.http.context import RequireCapability
from inc.api.http.router_scope import select_path_prefixes
from inc.api.http.routers_community import build_router as build_full_router

REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "community.discussions.moderate",
    "community.discussions.lock",
    "community.discussions.archive",
    "community.posts.moderate",
    "community.tags.manage",
    "community.read_admin",
    "community.search.rebuild",
    "community.purge",
)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    full = build_full_router(services, require_capability, require_authenticated)
    return select_path_prefixes(full, "/api/v1/admin/community/")
