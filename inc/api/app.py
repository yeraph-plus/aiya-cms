"""FastAPI composition root factory.

Contract source: context/spec/composition.md §7, context/spec/http-openapi.md.

``create_app`` builds the container for a manifest, mounts only the
manifest's routers, registers error normalization and request-id
middleware, and starts the manifest's workers in lifespan. Importing this
module creates nothing; only ``create_app`` does.
"""

from __future__ import annotations

import asyncio
import importlib
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from inc.api.config import DEFAULT_ISSUER
from inc.api.container import (
    ROUTER_BINDINGS,
    ApplicationContainer,
    Services,
    build_container,
)
from inc.api.http.admin_session_store import AdminSessionStore
from inc.api.http.context import (
    BearerVerifier,
    make_authenticated,
    make_require_capability,
)
from inc.api.http.errors import (
    internal_error_response,
    kernel_error_response,
    pydantic_validation_response,
    validation_error_response,
)
from inc.api.http.routers_health import build_router as build_health_router
from inc.kernel.boot import AppManifest
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time import Clock

_REQUEST_ID_HEADER = "x-request-id"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


class _RequestIdMiddleware:
    """Assigns and echoes X-Request-ID.

    Client values are accepted only when they match a safe charset; the
    echoed value is exactly what propagates as the trace id, so control
    characters or oversized values are replaced with a generated id.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        from starlette.datastructures import Headers

        headers = Headers(raw=scope.get("headers", []))
        raw = headers.get(_REQUEST_ID_HEADER)
        request_id = raw if raw and _REQUEST_ID_PATTERN.fullmatch(raw) else uuid.uuid4().hex
        scope["state"] = dict(scope.get("state", {}))
        scope["state"]["request_id"] = request_id

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers_list = list(message.get("headers", []))
                headers_list.append((_REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers_list
            await send(message)

        await self._app(scope, receive, send_wrapper)


_DEFAULT_HTTP_MESSAGES = {
    400: "bad request",
    401: "unauthorized",
    403: "forbidden",
    404: "not found",
    405: "method not allowed",
    409: "conflict",
    429: "too many requests",
    500: "internal error",
}


_OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "system", "description": "Liveness and readiness probes."},
    {"name": "auth", "description": "Authentication and account self-service."},
    {"name": "oidc", "description": "OIDC provider protocol endpoints."},
    {"name": "content", "description": "Published content reads."},
    {"name": "comments", "description": "Published comment reads and authenticated submission."},
    {"name": "discussions", "description": "Community discussions and published post streams."},
    {"name": "community-tags", "description": "Community tag directory and metadata."},
    {"name": "engagement", "description": "Views, likes, ratings and favorites."},
    {
        "name": "admin",
        "description": (
            "Administrator management endpoints; each requires backend capability grants."
        ),
    },
    {"name": "admin-users", "description": "User administration."},
    {"name": "admin-access", "description": "Roles, grants and permission keys."},
    {"name": "admin-content", "description": "Content lifecycle management."},
    {"name": "admin-comments", "description": "Comment moderation."},
    {"name": "admin-community", "description": "Community discussion, post and tag moderation."},
    {"name": "admin-taxonomy", "description": "Taxonomy dimensions and terms."},
    {"name": "admin-settings", "description": "Setting group management."},
    {"name": "admin-assets", "description": "Asset upload and metadata management."},
    {"name": "admin-content-bucket", "description": "Image hosting lifecycle management."},
    {"name": "admin-audit", "description": "Audit log queries."},
    {"name": "admin-execution", "description": "Kernel execution log queries."},
    {"name": "admin-points", "description": "Points balance and ledger administration."},
    {"name": "admin-dashboard", "description": "Capability-owned administrator statistics."},
    {"name": "admin-session", "description": "Administrator identity and active permissions."},
    {"name": "admin-engagement", "description": "Engagement projection administration."},
    {"name": "admin-membership", "description": "Membership subscriptions and renewals."},
    {
        "name": "admin-notifications",
        "description": "Notification delivery recovery and diagnostics.",
    },
    {"name": "admin-oidc", "description": "OIDC static client administration."},
]


def _http_exception_response(request: Request, exc: Any) -> Any:
    from inc.api.http.errors import error_body

    code = f"http.{exc.status_code}"
    detail = getattr(exc, "detail", None)
    message = (
        str(detail) if detail else _DEFAULT_HTTP_MESSAGES.get(exc.status_code, "request failed")
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(
            code=code,
            message=message,
            request_id=getattr(request.state, "request_id", None),
        ),
    )


def create_app(
    *,
    manifest: AppManifest,
    uow_factory: UoWFactory,
    clock: Clock,
    settings: Any,
    redis_url: str | None = None,
    start_workers: bool = True,
) -> FastAPI:
    environment = getattr(settings, "environment", "dev")
    if environment == "production" and not redis_url:
        raise ValueError("production requires a Redis URL for administrator sessions")
    container: ApplicationContainer = build_container(
        manifest=manifest, uow_factory=uow_factory, clock=clock, settings=settings
    )
    services: Services = container.services  # type: ignore[assignment]
    admin_session_store = AdminSessionStore(
        secret=getattr(settings, "admin_session_secret", "dev-admin-session-secret-change-me"),
        idle_seconds=getattr(settings, "admin_session_idle_seconds", 8 * 3600),
        absolute_seconds=getattr(settings, "admin_session_absolute_seconds", 14 * 86400),
        redis_url=redis_url,
        clock=clock,
    )
    verifier = BearerVerifier(
        services=services,
        issuer=getattr(settings, "issuer", DEFAULT_ISSUER),
        api_audience=getattr(settings, "api_audience", "aiya-admin"),
        admin_session_store=admin_session_store,
    )
    services.admin_session_store = admin_session_store
    require_capability = make_require_capability(verifier=verifier)
    require_authenticated = make_authenticated(verifier=verifier)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        try:
            if services.keys is not None:
                await services.keys.require_active_key()
            if start_workers:
                await container.start()
            yield
        finally:
            await container.stop()
            await admin_session_store.close()

    env = environment
    app = FastAPI(
        title=f"aiya-cms ({manifest.name})",
        version="0.1.0",
        docs_url="/docs" if env != "production" else None,
        redoc_url="/redoc" if env != "production" else None,
        openapi_url="/openapi.json",
        openapi_tags=_OPENAPI_TAGS,
        lifespan=lifespan,
    )

    cors_origins = getattr(settings, "cors_origins", ())
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
        )
    app.add_middleware(_RequestIdMiddleware)

    _register_error_handlers(app)

    # liveness/readiness always exist regardless of manifest scope
    async def _db_readiness() -> bool:
        async with uow_factory() as uow:
            await asyncio.wait_for(
                uow.session.execute(select(1)),
                timeout=2.0,
            )
        return True

    async def _redis_readiness() -> bool:
        return await asyncio.wait_for(admin_session_store.check_ready(), timeout=2.0)

    async def _application_readiness() -> bool:
        await _db_readiness()
        await _redis_readiness()
        return True

    app.include_router(
        build_health_router(
            manifest_name=manifest.name,
            capabilities=manifest.capabilities,
            routers=manifest.routers,
            readiness=_application_readiness,
        )
    )

    # fail-fast: every permission key used by a mounted router must be
    # registered by the enabled capabilities (boot.md §5)
    for router_name in manifest.routers:
        if router_name in ("health", "oidc"):
            continue
        binding = ROUTER_BINDINGS[router_name]
        if binding.module is None:
            raise KernelError(
                code="kernel.router_unbound",
                category=ErrorCategory.INTERNAL,
                message=f"router {router_name!r} has no HTTP module binding",
            )
        router_module = importlib.import_module(binding.module)
        for permission_key in getattr(router_module, "REQUIRED_PERMISSIONS", ()):
            services.permission_registry.require(permission_key)
        router = router_module.build_router(services, require_capability, require_authenticated)
        app.include_router(router)

    if "oidc" in manifest.routers:
        if services.oidc is None:
            raise KernelError(
                code="kernel.router_requires_missing",
                category=ErrorCategory.INTERNAL,
                message="router 'oidc' requires the oidc_provider capability",
            )
        from inc.capabilities.oidc_provider.api import OidcHttpServices, build_router

        oidc_services = OidcHttpServices(
            issuer=getattr(settings, "issuer", DEFAULT_ISSUER),
            uow_factory=services.uow_factory,
            clock=services.clock,
            keys=services.oidc["keys"],
            authenticator=services.adapters["oidc.subject_authenticator"],
            authorization=services.oidc["authorization"],
            token=services.oidc["token"],
            userinfo=services.oidc["userinfo"],
            revocation=services.oidc["revocation"],
            logout=services.oidc["logout"],
            secure_cookies=getattr(settings, "secure_cookies", False),
            trusted_proxy_cidrs=getattr(settings, "trusted_proxy_cidrs", ()),
        )
        app.include_router(build_router(oidc_services))

    app.state.container = container
    app.state.services = services
    return app


def _register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(KernelError, kernel_error_response)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, cast(Any, validation_error_response))
    app.add_exception_handler(ValidationError, cast(Any, pydantic_validation_response))
    app.add_exception_handler(StarletteHTTPException, _http_exception_response)
    app.add_exception_handler(Exception, internal_error_response)
