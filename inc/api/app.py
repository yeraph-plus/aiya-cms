"""FastAPI application factory and M1 middleware composition root."""

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from inc.kernel.config import Settings, get_settings
from inc.kernel.db import new_uuid7
from inc.kernel.errors import (
    AppError,
    app_error_handler,
    request_validation_handler,
    unhandled_exception_handler,
)
from inc.kernel.logging import bind_context, setup_logging
from inc.setting import bind as bind_runtime_settings
from inc.setting import reset as reset_runtime_settings

from .routes import router
from .wiring import build_container

_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the fully wired M1 application."""

    resolved_settings = settings or get_settings()
    setup_logging(resolved_settings)
    container = build_container(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        container.scheduler.start()
        await container.scheduler.start_listener()
        try:
            yield
        finally:
            await container.scheduler.stop()
            await container.event_bus.wait_idle()
            close_cache = getattr(container.cache, "close", None)
            if close_cache is not None:
                await close_cache()
            await container.database.dispose()

    application = FastAPI(
        title="aiya-cms",
        version="0.1.0",
        docs_url="/docs",
        lifespan=lifespan,
    )
    application.state.container = container
    application.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    from fastapi.exceptions import RequestValidationError

    application.add_exception_handler(
        RequestValidationError,
        request_validation_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @application.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        candidate = request.headers.get("X-Request-ID", "")
        request_id = candidate if _REQUEST_ID.fullmatch(candidate) else str(new_uuid7())
        bind_context(request_id=request_id, route=request.url.path)
        settings_token = bind_runtime_settings(container.runtime_settings)
        authorization = request.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            try:
                request.state.principal = await container.auth.principal_from_access(
                    authorization[7:].strip()
                )
            except AppError as exc:
                request.state.auth_error = exc
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            reset_runtime_settings(settings_token)

    @application.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "environment": resolved_settings.env}

    application.include_router(router)
    return application
