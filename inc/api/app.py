"""FastAPI composition root factory.

Contract source: context/spec/composition.md §7, context/spec/http-openapi.md.

``create_app`` builds the container for a manifest, mounts only the
manifest's routers, registers error normalization and request-id
middleware, and starts the manifest's workers in lifespan. Importing this
module creates nothing; only ``create_app`` does.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from inc.api.container import ApplicationContainer, Services, build_container
from inc.api.http.context import BearerVerifier, make_require_capability
from inc.api.http.errors import (
    internal_error_response,
    kernel_error_response,
    pydantic_validation_response,
    validation_error_response,
)
from inc.api.http.routers_access import build_router as build_access_router
from inc.api.http.routers_assets import build_router as build_assets_router
from inc.api.http.routers_audit import build_router as build_audit_router
from inc.api.http.routers_auth import build_router as build_auth_router
from inc.api.http.routers_content import build_router as build_content_router
from inc.api.http.routers_health import build_router as build_health_router
from inc.api.http.routers_identity import build_router as build_identity_router
from inc.api.http.routers_settings import build_router as build_settings_router
from inc.api.http.routers_taxonomy import build_router as build_taxonomy_router
from inc.kernel.boot import AppManifest
from inc.kernel.db import UoWFactory
from inc.kernel.errors import KernelError
from inc.kernel.time import Clock

_ROUTER_FACTORIES: dict[str, Any] = {
    "health": build_health_router,
    "identity": build_identity_router,
    "access": build_access_router,
    "content": build_content_router,
    "taxonomy": build_taxonomy_router,
    "settings": build_settings_router,
    "assets": build_assets_router,
    "audit": build_audit_router,
    "auth": build_auth_router,
}

_REQUEST_ID_HEADER = "x-request-id"


class _RequestIdMiddleware:
    """Assigns and echoes X-Request-ID."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        from starlette.datastructures import Headers

        headers = Headers(raw=scope.get("headers", []))
        raw = headers.get(_REQUEST_ID_HEADER)
        request_id = raw if raw and len(raw) <= 128 else uuid.uuid4().hex
        scope["state"] = dict(scope.get("state", {}))
        scope["state"]["request_id"] = request_id

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers_list = list(message.get("headers", []))
                headers_list.append((_REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers_list
            await send(message)

        await self._app(scope, receive, send_wrapper)


def _http_exception_response(request: Request, exc: Any) -> Any:
    from inc.api.http.errors import error_body

    code = f"http.{exc.status_code}"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(
            code=code,
            message=str(exc.detail) if getattr(exc, "detail", None) else "not found",
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
    require_capability = make_require_capability(
        verifier=BearerVerifier(
            services=services,
            issuer=getattr(settings, "issuer", "http://localhost:8080"),
            api_audience=getattr(settings, "api_audience", "aiya-admin"),
        )
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        if start_workers:
            await container.start()
        try:
            yield
        finally:
            await container.stop()

    app = FastAPI(
        title=f"aiya-cms ({manifest.name})",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
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
    app.include_router(
        build_health_router(
            manifest_name=manifest.name,
            capabilities=manifest.capabilities,
            routers=manifest.routers,
        )
    )

    for router_name in manifest.routers:
        if router_name == "health":
            continue
        factory = _ROUTER_FACTORIES.get(router_name)
        if factory is None:
            continue
        router = factory(services, require_capability)
        app.include_router(router)

    if "oidc_provider" in manifest.capabilities and services.oidc is not None:
        from inc.capabilities.oidc_provider.api import OidcHttpServices, build_router

        oidc_services = OidcHttpServices(
            issuer=getattr(settings, "issuer", "http://localhost:8080"),
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
