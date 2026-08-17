"""Helpers for exposing an explicit subset of a combined legacy router."""

from __future__ import annotations

from fastapi import APIRouter


def select_path_prefixes(router: APIRouter, *prefixes: str) -> APIRouter:
    selected = APIRouter()
    selected.routes.extend(
        route
        for route in router.routes
        if any(getattr(route, "path", "").startswith(prefix) for prefix in prefixes)
    )
    return selected
