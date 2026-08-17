"""OIDC protocol HTTP endpoints.

Contract source: context/spec/capabilities/oidc-provider.md §3.

This module exports a pure router factory; nothing is mounted at import.
Protocol errors map to standard OAuth/OIDC error responses, never the
business error DTO. The browser session cookie is HttpOnly, SameSite=Lax
and Secure in production; the session row is created server-side and only
its digest is stored.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
from datetime import UTC, timedelta
from typing import Any
from urllib.parse import urlencode

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
from inc.kernel.security import resolve_client_ip
from inc.kernel.time import Clock

SESSION_LIFETIME_SECONDS = 3600
LOGIN_FAILURE_LIMIT = 5
LOGIN_IP_FAILURE_LIMIT = 30
LOGIN_FAILURE_WINDOW_SECONDS = 300
LOGIN_FAILURE_MAX_KEYS = 10_000


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
        trusted_proxy_cidrs: tuple[str, ...] = (),
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
        self.trusted_proxy_cidrs = trusted_proxy_cidrs
        self._login_failures: dict[str, list[Any]] = {}

    def login_allowed(self, key: str, *, limit: int = LOGIN_FAILURE_LIMIT) -> bool:
        now = self.clock.utc_now()
        attempts = self._fresh_login_attempts(key, now)
        return len(attempts) < limit

    def record_login_failure(self, key: str) -> None:
        now = self.clock.utc_now()
        attempts = self._fresh_login_attempts(key, now)
        if key not in self._login_failures and len(self._login_failures) >= LOGIN_FAILURE_MAX_KEYS:
            self._login_failures.pop(next(iter(self._login_failures)), None)
        self._login_failures[key] = [*attempts, now]

    def clear_login_failures(self, key: str) -> None:
        self._login_failures.pop(key, None)

    def _fresh_login_attempts(self, key: str, now: Any) -> list[Any]:
        attempts = [
            timestamp
            for timestamp in self._login_failures.get(key, [])
            if (now - timestamp).total_seconds() < LOGIN_FAILURE_WINDOW_SECONDS
        ]
        if attempts:
            self._login_failures[key] = attempts
        else:
            self._login_failures.pop(key, None)
        return attempts

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
    response = JSONResponse(status_code=error.http_status, content=body)
    if error.code == "invalid_client":
        response.headers["WWW-Authenticate"] = 'Basic realm="oidc"'
    return response


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


def _client_credentials(request: Request, form: dict[str, Any]) -> tuple[str, str | None]:
    """Read public body credentials or RFC 6749 HTTP Basic credentials."""

    authorization = request.headers.get("Authorization")
    if not authorization:
        return _required(form, "client_id"), _first(form, "client_secret")

    scheme, separator, encoded = authorization.partition(" ")
    if separator != " " or scheme.lower() != "basic" or not encoded:
        raise OidcError("invalid_client", "unsupported client authentication", http_status=401)
    if _first(form, "client_secret") is not None:
        raise OidcError("invalid_request", "multiple client authentication methods are not allowed")
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise OidcError("invalid_client", "invalid client credentials", http_status=401) from exc
    client_id, separator, client_secret = decoded.partition(":")
    if separator != ":" or not client_id or not client_secret:
        raise OidcError("invalid_client", "invalid client credentials", http_status=401)
    body_client_id = _first(form, "client_id")
    if body_client_id is not None and body_client_id != client_id:
        raise OidcError("invalid_client", "conflicting client identifiers", http_status=401)
    return client_id, client_secret


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "").lower()


def _login_form(params: dict[str, str]) -> str:
    locale = "en" if "en" in params.get("ui_locales", "").split() else "zh-CN"
    labels = (
        {"title": "Sign in", "username": "Username", "password": "Password"}
        if locale == "en"
        else {"title": "登录", "username": "用户名", "password": "密码"}
    )
    hidden = "".join(
        f'<input type="hidden" name="{_html_escape(k)}" value="{_html_escape(v)}"/>'
        for k, v in params.items()
    )
    return (
        f'<!doctype html><html lang="{locale}"><head><meta charset="utf-8"/>'
        f"<title>{labels['title']}</title></head><body>"
        '<form method="post" action="/oidc/login">'
        f"<label>{labels['username']} "
        '<input type="text" name="username" autocomplete="username"/></label><br/>'
        f"<label>{labels['password']} "
        '<input type="password" name="password" autocomplete="current-password"/></label><br/>'
        f"{hidden}"
        f'<button type="submit">{labels["title"]}</button>'
        "</form></body></html>"
    )


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    )


def build_router(services: OidcHttpServices) -> APIRouter:
    """Factory: returns a router; mounting is the composition root's job."""

    router = APIRouter(tags=["oidc"])

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
        wants_json = _wants_json(request)
        username = _required(form, "username")
        password = _required(form, "password")
        client_id = _first(form, "client_id") or "browser"
        client_host = resolve_client_ip(
            peer=request.client.host if request.client else None,
            forwarded_for=request.headers.get("x-forwarded-for"),
            trusted_proxy_cidrs=services.trusted_proxy_cidrs,
        )
        limiter_key = f"{client_host}:{client_id}:{username.strip().casefold()}"
        ip_limiter_key = f"{client_host}:{client_id}:*"
        if not services.login_allowed(limiter_key) or not services.login_allowed(
            ip_limiter_key, limit=LOGIN_IP_FAILURE_LIMIT
        ):
            return _error_response(
                OidcError(
                    "temporarily_unavailable",
                    "too many login attempts; try again later",
                    http_status=429,
                )
            )
        subject_id = await services.authenticator.authenticate(username, password)
        if subject_id is None:
            services.record_login_failure(limiter_key)
            services.record_login_failure(ip_limiter_key)
            if wants_json:
                return _error_response(
                    OidcError("access_denied", "invalid username or password", http_status=401)
                )
            # Never echo the typed password back into the 401 page.
            redacted = {k: str(v) for k, v in form.items() if k != "password"}
            return HTMLResponse(_login_form(redacted), status_code=401)
        services.clear_login_failures(limiter_key)
        # Preserve the original authorize parameters so the follow-up GET can
        # issue a code; only the credentials are stripped.
        authorize_params = {k: str(v) for k, v in form.items() if k not in ("username", "password")}
        query = urlencode(authorize_params, doseq=True)
        if wants_json:
            try:
                callback = await services.authorization.issue_code(
                    client_id=_required(form, "client_id"),
                    redirect_uri=_required(form, "redirect_uri"),
                    response_type=_required(form, "response_type"),
                    scope=_required(form, "scope"),
                    state=_first(form, "state"),
                    nonce=_first(form, "nonce"),
                    code_challenge=_first(form, "code_challenge"),
                    code_challenge_method=_first(form, "code_challenge_method"),
                    subject_id=subject_id,
                    session_handle=None,
                )
            except OidcError as error:
                return _error_response(error)
            handle = await services.establish_session(subject_id, client_id)
            json_response = JSONResponse({"redirect_uri": callback})
            json_response.headers["Cache-Control"] = "no-store"
            json_response.headers["Pragma"] = "no-cache"
            json_response.set_cookie(
                SESSION_COOKIE_NAME,
                value=handle,
                httponly=True,
                samesite="lax",
                secure=services.secure_cookies,
                max_age=SESSION_LIFETIME_SECONDS,
            )
            return json_response

        handle = await services.establish_session(subject_id, client_id)
        redirect_response = RedirectResponse(f"/oidc/authorize?{query}", status_code=302)
        redirect_response.set_cookie(
            SESSION_COOKIE_NAME,
            value=handle,
            httponly=True,
            samesite="lax",
            secure=services.secure_cookies,
            max_age=SESSION_LIFETIME_SECONDS,
        )
        return redirect_response

    @router.post("/oidc/token")
    async def token(request: Request) -> Response:
        form = dict(await request.form())
        grant_type = _required(form, "grant_type")
        try:
            client_id, client_secret = _client_credentials(request, form)
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
            client_id, client_secret = _client_credentials(request, form)
            await services.revocation.revoke(
                client_id=client_id,
                token=_required(form, "token"),
                token_type_hint=_first(form, "token_type_hint"),
                client_secret=client_secret,
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
