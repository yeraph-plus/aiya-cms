"""OIDC protocol HTTP endpoints.

Contract source: context/spec/capabilities/oidc-provider.md §3.

This module exports a pure router factory; nothing is mounted at import.
Protocol errors map to standard OAuth/OIDC error responses, never the
business error DTO. The browser session cookie is HttpOnly, SameSite=Lax
and Secure in production; the session row is created server-side and only
its digest is stored.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from inc.capabilities.oidc_provider.keys import KeyService
from inc.capabilities.oidc_provider.models import OidcSession, StringList
from inc.capabilities.oidc_provider.ports import SubjectAuthenticator
from inc.capabilities.oidc_provider.schemas import OidcError
from inc.capabilities.oidc_provider.services import (
    SESSION_COOKIE_NAME,
    AuthorizationService,
    LogoutService,
    RevocationService,
    TokenService,
    UserInfoService,
)
from inc.kernel.db import UoWFactory
from inc.kernel.time import Clock

SESSION_LIFETIME_SECONDS = 3600


class OidcHttpServices:
    """Aggregated services handed to the router factory."""

    def __init__(
        self,
        *,
        issuer: str,
        uow_factory: UoWFactory,
        clock: Clock,
        keys: KeyService,
        authenticator: SubjectAuthenticator,
        authorization: AuthorizationService,
        token: TokenService,
        userinfo: UserInfoService,
        revocation: RevocationService,
        logout: LogoutService,
        secure_cookies: bool = True,
    ) -> None:
        self.issuer = issuer
        self.uow_factory = uow_factory
        self.clock = clock
        self.keys = keys
        self.authenticator = authenticator
        self.authorization = authorization
        self.token = token
        self.userinfo = userinfo
        self.revocation = revocation
        self.logout = logout
        self.secure_cookies = secure_cookies

    async def establish_session(self, subject_id: str, client_id: str) -> str:
        """Create an OidcSession; returns the raw cookie value."""

        handle = secrets.token_urlsafe(48)
        async with self.uow_factory() as uow:
            uow.session.add(
                OidcSession(
                    subject_id=subject_id,
                    client_id=client_id,
                    session_handle=_digest(handle),
                    auth_time=self.clock.utc_now(),
                    acr="1",
                    amr=StringList(items=["pwd"]),
                    expires_at=self.clock.utc_now() + timedelta(seconds=SESSION_LIFETIME_SECONDS),
                )
            )
            await uow.commit()
        return handle

    async def subject_from_session(self, cookie: str | None) -> str | None:  # type: ignore[return]
        if cookie is None:
            return None
        async with self.uow_factory() as uow:
            row: OidcSession | None = (
                (
                    await uow.session.execute(
                        select(OidcSession).where(OidcSession.session_handle == _digest(cookie))
                    )
                )
                .scalars()
                .first()
            )
            if (
                row is None
                or row.revoked_at is not None
                or _ensure_utc(row.expires_at) < self.clock.utc_now()
            ):
                return None
            return row.subject_id


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ensure_utc(value: Any) -> Any:
    """SQLite drops tzinfo; persisted times are always UTC."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _error_response(error: OidcError) -> JSONResponse:
    body: dict[str, Any] = {"error": error.code}
    if error.description:
        body["error_description"] = error.description
    return JSONResponse(status_code=error.http_status, content=body)


def _first(form: dict[str, Any], key: str) -> str | None:
    value = form.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return str(value) if value is not None else None


def _required(form: dict[str, Any], key: str) -> str:
    value = _first(form, key)
    if not value:
        raise OidcError("invalid_request", f"missing required parameter {key}")
    return value


def _login_form(params: dict[str, str]) -> str:
    hidden = "".join(
        f'<input type="hidden" name="{k}" value="{_html_escape(v)}"/>' for k, v in params.items()
    )
    return (
        "<!doctype html><html><body>"
        '<form method="post" action="/oidc/login">'
        '<label>Username <input type="text" name="username" autocomplete="username"/></label><br/>'
        "<label>Password "
        '<input type="password" name="password" autocomplete="current-password"/></label><br/>'
        f"{hidden}"
        '<button type="submit">Sign in</button>'
        "</form></body></html>"
    )


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    )


def build_router(services: OidcHttpServices) -> APIRouter:
    """Factory: returns a router; mounting is the composition root's job."""

    router = APIRouter()

    @router.get("/.well-known/openid-configuration")
    async def discovery() -> JSONResponse:
        from inc.capabilities.oidc_provider.discovery import DiscoveryService

        return JSONResponse(DiscoveryService(issuer=services.issuer).configuration())

    @router.get("/oidc/jwks")
    async def jwks() -> JSONResponse:
        return JSONResponse(await services.keys.public_jwks())

    @router.get("/oidc/authorize")
    async def authorize(request: Request) -> Response:
        params = dict(request.query_params)
        subject_id = await services.subject_from_session(request.cookies.get(SESSION_COOKIE_NAME))
        if subject_id is None:
            return HTMLResponse(_login_form(params), status_code=200)
        try:
            redirect = await services.authorization.issue_code(
                client_id=_required(params, "client_id"),
                redirect_uri=_required(params, "redirect_uri"),
                response_type=_required(params, "response_type"),
                scope=_required(params, "scope"),
                state=params.get("state"),
                nonce=params.get("nonce"),
                code_challenge=params.get("code_challenge"),
                code_challenge_method=params.get("code_challenge_method"),
                subject_id=subject_id,
                session_handle=request.cookies.get(SESSION_COOKIE_NAME),
            )
        except OidcError as error:
            return _error_response(error)
        return RedirectResponse(redirect, status_code=302)

    @router.post("/oidc/login")
    async def login(request: Request) -> Response:
        form = dict(await request.form())
        username = _required(form, "username")
        password = _required(form, "password")
        client_id = _first(form, "client_id") or "browser"
        subject_id = await services.authenticator.authenticate(username, password)
        if subject_id is None:
            return HTMLResponse(_login_form({k: str(v) for k, v in form.items()}), status_code=401)
        handle = await services.establish_session(subject_id, client_id)
        response = RedirectResponse("/oidc/authorize", status_code=302)
        response.set_cookie(
            SESSION_COOKIE_NAME,
            value=handle,
            httponly=True,
            samesite="lax",
            secure=services.secure_cookies,
            max_age=SESSION_LIFETIME_SECONDS,
        )
        return response

    @router.post("/oidc/token")
    async def token(request: Request) -> Response:
        form = dict(await request.form())
        grant_type = _required(form, "grant_type")
        client_id = _required(form, "client_id")
        client_secret = _first(form, "client_secret")
        try:
            if grant_type == "authorization_code":
                result = await services.token.exchange(
                    client_id=client_id,
                    code=_required(form, "code"),
                    redirect_uri=_required(form, "redirect_uri"),
                    code_verifier=_first(form, "code_verifier"),
                    client_secret=client_secret,
                )
            elif grant_type == "refresh_token":
                result = await services.token.refresh(
                    client_id=client_id,
                    refresh_token=_required(form, "refresh_token"),
                    client_secret=client_secret,
                )
            else:
                raise OidcError("unsupported_grant_type", f"unsupported grant_type {grant_type!r}")
        except OidcError as error:
            return _error_response(error)
        response = JSONResponse(result.model_dump(exclude_none=True))
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response

    @router.get("/oidc/userinfo")
    async def userinfo(request: Request) -> Response:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return _error_response(OidcError("invalid_token", "bearer token required"))
        try:
            claims = await services.userinfo.userinfo(auth.removeprefix("Bearer ").strip())
        except OidcError as error:
            return _error_response(error)
        response = JSONResponse(claims)
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.post("/oidc/revoke")
    async def revoke(request: Request) -> Response:
        form = dict(await request.form())
        try:
            await services.revocation.revoke(
                client_id=_required(form, "client_id"),
                token=_required(form, "token"),
                token_type_hint=_first(form, "token_type_hint"),
                client_secret=_first(form, "client_secret"),
            )
        except OidcError as error:
            return _error_response(error)
        return Response(status_code=200)

    @router.get("/oidc/logout")
    async def logout(request: Request) -> Response:
        params = dict(request.query_params)
        try:
            redirect = await services.logout.logout(
                id_token_hint=params.get("id_token_hint"),
                post_logout_redirect_uri=params.get("post_logout_redirect_uri"),
                session_cookie=request.cookies.get(SESSION_COOKIE_NAME),
            )
        except OidcError as error:
            return _error_response(error)
        response = (
            RedirectResponse(redirect, status_code=302) if redirect else Response(status_code=204)
        )
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    return router
