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
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from inc.api.container import ApplicationContainer, Services, build_container
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
from inc.kernel.errors import KernelError
from inc.kernel.time import Clock

_ROUTER_FACTORIES: dict[str, Any] = {
    "identity": importlib.import_module("inc.api.http.routers_identity"),
    "access": importlib.import_module("inc.api.http.routers_access"),
    "content": importlib.import_module("inc.api.http.routers_content"),
    "taxonomy": importlib.import_module("inc.api.http.routers_taxonomy"),
    "settings": importlib.import_module("inc.api.http.routers_settings"),
    "assets": importlib.import_module("inc.api.http.routers_assets"),
    "audit": importlib.import_module("inc.api.http.routers_audit"),
    "auth": importlib.import_module("inc.api.http.routers_auth"),
    "check_in": importlib.import_module("inc.api.http.routers_check_in"),
    "points": importlib.import_module("inc.api.http.routers_points"),
    "points_admin": importlib.import_module("inc.api.http.routers_points_admin"),
    "point_purchase": importlib.import_module("inc.api.http.routers_point_purchase"),
    "payments": importlib.import_module("inc.api.http.routers_payments"),
    "membership_purchase": importlib.import_module("inc.api.http.routers_membership_purchase"),
}

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
    {"name": "check-in", "description": "Daily check-in; rewards points."},
    {"name": "points", "description": "Points balance self-service reads."},
    {"name": "point-purchase", "description": "Buy points via the trusted offer catalog."},
    {
        "name": "membership-purchase",
        "description": "Buy membership via the trusted offer catalog.",
    },
    {"name": "webhooks", "description": "Provider webhook callbacks (signature verified)."},
    {
        "name": "admin",
        "description": (
            "Administrator management endpoints; each requires backend capability grants."
        ),
    },
    {"name": "admin-users", "description": "User administration."},
    {"name": "admin-access", "description": "Roles, grants and permission keys."},
    {"name": "admin-content", "description": "Content lifecycle management."},
    {"name": "admin-taxonomy", "description": "Taxonomy dimensions and terms."},
    {"name": "admin-settings", "description": "Setting group management."},
    {"name": "admin-assets", "description": "Asset upload and metadata management."},
    {"name": "admin-audit", "description": "Audit log queries."},
    {"name": "admin-payments", "description": "Payment order administration."},
    {"name": "admin-points", "description": "Points balance and ledger administration."},
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
    start_workers: bool = True,
) -> FastAPI:
    container: ApplicationContainer = build_container(
        manifest=manifest, uow_factory=uow_factory, clock=clock, settings=settings
    )
    services: Services = container.services  # type: ignore[assignment]
    verifier = BearerVerifier(
        services=services,
        issuer=getattr(settings, "issuer", "http://127.0.0.1:8080"),
        api_audience=getattr(settings, "api_audience", "aiya-admin"),
    )
    require_capability = make_require_capability(verifier=verifier)
    require_authenticated = make_authenticated(verifier=verifier)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        try:
            if start_workers:
                await container.start()
            yield
        finally:
            await container.stop()

    env = getattr(settings, "environment", "dev")
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
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
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

    app.include_router(
        build_health_router(
            manifest_name=manifest.name,
            capabilities=manifest.capabilities,
            routers=manifest.routers,
            readiness=_db_readiness,
        )
    )

    # fail-fast: every permission key used by a mounted router must be
    # registered by the enabled capabilities (boot.md §5)
    for router_name in manifest.routers:
        if router_name in ("health", "oidc"):
            continue
        router_module = _ROUTER_FACTORIES.get(router_name)
        if router_module is None:
            continue
        for permission_key in getattr(router_module, "REQUIRED_PERMISSIONS", ()):
            services.permission_registry.require(permission_key)
        router = router_module.build_router(services, require_capability, require_authenticated)
        app.include_router(router)

    if "oidc" in manifest.routers and services.oidc is not None:
        from inc.capabilities.oidc_provider.api import OidcHttpServices, build_router

        oidc_services = OidcHttpServices(
            issuer=getattr(settings, "issuer", "http://127.0.0.1:8080"),
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
        )
        app.include_router(build_router(oidc_services))

    app.state.container = container
    app.state.services = services
    return app


def _register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(KernelError, kernel_error_response)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_response)  # type: ignore[arg-type]
    app.add_exception_handler(ValidationError, pydantic_validation_response)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_response)
    app.add_exception_handler(Exception, internal_error_response)
