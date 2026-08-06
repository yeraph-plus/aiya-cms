"""HTTP dependency boundaries for the M1 API."""

from typing import Any, cast

from fastapi import Request

from inc.kernel.auth.errors import AUTH_001
from inc.kernel.errors import AppError
from inc.kernel.security import Principal, get_current_principal

from .wiring import AppContainer


def get_container(request: Request) -> AppContainer:
    return cast(AppContainer, request.app.state.container)


def get_auth(request: Request) -> Any:
    return get_container(request).auth


def get_identity(request: Request) -> Any:
    return get_container(request).identity


def get_rbac(request: Request) -> Any:
    return get_container(request).rbac


def get_audit(request: Request) -> Any:
    return get_container(request).audit


def get_runtime_settings(request: Request) -> Any:
    return get_container(request).runtime_settings


def get_mail(request: Request) -> Any:
    return get_container(request).mail


def get_content(request: Request) -> Any:
    return get_container(request).content


def get_taxonomy(request: Request) -> Any:
    return get_container(request).taxonomy


def get_comments(request: Request) -> Any:
    return get_container(request).comments


def get_interactions(request: Request) -> Any:
    return get_container(request).interactions


def get_scheduler(request: Request) -> Any:
    return get_container(request).scheduler


async def require_authenticated(request: Request) -> Principal:
    auth_error = getattr(request.state, "auth_error", None)
    if isinstance(auth_error, AppError):
        raise auth_error
    principal = await get_current_principal(request)
    if principal.is_anonymous:
        raise AppError(AUTH_001)
    return principal


async def optional_principal(request: Request) -> Principal:
    auth_error = getattr(request.state, "auth_error", None)
    if isinstance(auth_error, AppError):
        raise auth_error
    return await get_current_principal(request)
