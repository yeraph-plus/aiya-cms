"""Administrator session bootstrap within the /admin transport boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.admin_session_store import AdminAuthTransaction
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.access.schemas import Principal
from inc.capabilities.oidc_provider import load_public_key, verify_jwt
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time import Clock


class AdminSessionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str
    username: str
    display_name: str | None = None
    avatar_asset_id: str | None = None
    status: str
    capabilities: list[str] = Field(default_factory=list)
    csrf_token: str | None = None
    idle_expires_at: datetime | None = None
    absolute_expires_at: datetime | None = None


class AdminAuthTransactionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    redirect_uri: str | None = Field(default=None, max_length=2048)


class AdminAuthTransactionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str


class AdminSessionExchangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=512)
    client_id: str = Field(default="admin", min_length=1, max_length=200)
    redirect_uri: str | None = Field(default=None, max_length=2048)
    code_verifier: str | None = Field(default=None, max_length=512)


REQUIRED_PERMISSIONS: tuple[str, ...] = ()


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any,
) -> APIRouter:
    del require_capability
    router = APIRouter(prefix="/api/v1/admin", tags=["admin", "admin-session"])

    @router.get("/session", response_model=AdminSessionDTO)
    async def session(
        response: Response, request: Request, ctx: AppContext = Depends(require_authenticated())
    ) -> AdminSessionDTO:
        _require_admin_client(ctx)
        return await _render_session(response, services, ctx, request=request)

    @router.post("/session", response_model=AdminSessionDTO)
    async def refresh_session(
        response: Response,
        request: Request,
        body: AdminSessionExchangeInput | None = Body(default=None),
    ) -> AdminSessionDTO:
        if body is not None:
            store = services.admin_session_store
            if store is None or services.oidc is None:
                raise KernelError(
                    code="api.session_unavailable",
                    category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    message="administrator session exchange is unavailable",
                )
            if body.client_id != "admin":
                raise KernelError(
                    code="api.session_exchange_failed",
                    category=ErrorCategory.UNAUTHORIZED,
                    message="administrator login client is not allowed",
                )
            transaction = await store.consume_transaction(body.state)
            if transaction is None:
                raise KernelError(
                    code="api.session_transaction_invalid",
                    category=ErrorCategory.UNAUTHORIZED,
                    message="administrator login transaction is invalid or expired",
                )
            if body.redirect_uri is not None and body.redirect_uri != transaction.redirect_uri:
                raise KernelError(
                    code="api.session_transaction_invalid",
                    category=ErrorCategory.UNAUTHORIZED,
                    message="administrator login redirect does not match transaction",
                )
            try:
                tokens = await services.oidc["token"].exchange(
                    client_id=body.client_id,
                    code=body.code,
                    redirect_uri=transaction.redirect_uri,
                    code_verifier=body.code_verifier or transaction.code_verifier,
                )
                id_token = tokens.id_token
                if not id_token:
                    raise ValueError("missing id token")
                jwks = await services.oidc["keys"].public_jwks()
                public_keys = {
                    item["kid"]: load_public_key(item)
                    for item in jwks.get("keys", [])
                    if isinstance(item, dict) and item.get("kid")
                }
                id_claims = verify_jwt(
                    id_token,
                    public_keys=public_keys,
                    audience=body.client_id,
                    issuer=getattr(services.settings, "issuer", ""),
                )
                if id_claims.get("nonce") != transaction.nonce:
                    raise ValueError("id token nonce mismatch")
                claims = await services.oidc["userinfo"].userinfo(tokens.access_token)
            except Exception as exc:
                # OIDC protocol details must not leak through the admin error
                # envelope; the exchange is intentionally one-shot.
                raise KernelError(
                    code="api.session_exchange_failed",
                    category=ErrorCategory.UNAUTHORIZED,
                    message="administrator login exchange failed",
                ) from exc
            subject_id = str(claims.get("sub", ""))
            if not subject_id:
                raise KernelError(
                    code="api.session_exchange_failed",
                    category=ErrorCategory.UNAUTHORIZED,
                    message="administrator login exchange returned no subject",
                )
            token, csrf = await store.create(subject_id)
            _set_session_cookies(response, services, token, csrf)
            subject = await services.identity_queries.get_subject(subject_id)
            if subject is None or subject.status != "active":
                raise KernelError(
                    code="identity.not_found",
                    category=ErrorCategory.NOT_FOUND,
                    message="subject disappeared",
                )
            principal = Principal(subject_id=subject_id, status="active")
            capabilities = await services.authorize.capabilities_of(principal)
            now = _epoch_seconds(services.clock)
            return AdminSessionDTO(
                subject_id=subject.id,
                username=subject.username,
                display_name=subject.display_name,
                avatar_asset_id=subject.avatar_asset_id,
                status=subject.status,
                capabilities=sorted(capabilities),
                csrf_token=csrf,
                idle_expires_at=datetime.fromtimestamp(
                    now + services.settings.admin_session_idle_seconds, UTC
                ),
                absolute_expires_at=datetime.fromtimestamp(
                    now + services.settings.admin_session_absolute_seconds, UTC
                ),
            )

        # Compatibility path for a freshly exchanged OIDC bearer token.  It
        # immediately upgrades the transport to the HttpOnly cookie and the
        # SPA discards the bearer afterward.
        from fastapi.security import HTTPAuthorizationCredentials

        from inc.api.http.context import BearerVerifier

        raw = request.headers.get("authorization", "")
        credentials = None
        if raw.lower().startswith("bearer "):
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw[7:].strip())
        verifier = BearerVerifier(
            services=services,
            issuer=getattr(services.settings, "issuer", ""),
            api_audience=getattr(services.settings, "api_audience", "aiya-admin"),
            admin_session_store=services.admin_session_store,
        )
        ctx = await verifier.verify(credentials, request)
        _require_admin_client(ctx)
        return await _render_session(response, services, ctx, request=request)

    @router.post("/session/logout", status_code=204)
    async def logout(
        response: Response, request: Request, ctx: AppContext = Depends(require_authenticated())
    ) -> None:
        _require_admin_client(ctx)
        store = services.admin_session_store
        if store is not None:
            await store.revoke(request.cookies.get("aiya_admin_session"))
        response.delete_cookie("aiya_admin_session", path="/")
        response.delete_cookie("aiya_admin_csrf", path="/")

    @router.post("/auth/transactions")
    async def create_transaction(
        body: AdminAuthTransactionInput | None = Body(default=None),
    ) -> AdminAuthTransactionDTO:
        store = services.admin_session_store
        if store is None:
            raise KernelError(
                code="api.session_unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="administrator session store is unavailable",
            )
        transaction: AdminAuthTransaction = await store.create_transaction(
            redirect_uri=(body.redirect_uri if body and body.redirect_uri else "/")
        )
        return AdminAuthTransactionDTO(
            transaction_id=transaction.state,
            state=transaction.state,
            nonce=transaction.nonce,
            code_verifier=transaction.code_verifier,
            redirect_uri=transaction.redirect_uri,
        )

    return router


def _set_session_cookies(response: Response, services: Services, token: str, csrf: str) -> None:
    secure = bool(getattr(services.settings, "secure_cookies", False))
    max_age = getattr(services.settings, "admin_session_absolute_seconds", 14 * 86400)
    response.set_cookie(
        "aiya_admin_session",
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    response.set_cookie(
        "aiya_admin_csrf",
        csrf,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )


def _require_admin_client(ctx: AppContext) -> None:
    """Cookie sessions have no OIDC client; bearer sessions must be admin."""

    if ctx.principal.auth_method == "bearer" and ctx.principal.client_id != "admin":
        raise KernelError(
            code="api.unauthorized",
            category=ErrorCategory.UNAUTHORIZED,
            message="administrator session requires the admin client",
        )


async def _render_session(
    response: Response, services: Services, ctx: AppContext, *, request: Request | None = None
) -> AdminSessionDTO:
    subject = await services.identity_queries.get_subject(ctx.principal.subject_id)
    if subject is None:
        raise KernelError(
            code="identity.not_found",
            category=ErrorCategory.NOT_FOUND,
            message="subject disappeared",
        )
    store = services.admin_session_store
    record: Any | None = None
    created_at: int | None = None
    last_seen: int | None = None
    if store is not None and ctx.principal.auth_method == "bearer":
        token, csrf = await store.create(subject.id)
        _set_session_cookies(response, services, token, csrf)
        now = _epoch_seconds(services.clock)
        created_at = now
        last_seen = now
    elif store is not None and request is not None:
        record = await store.load(request.cookies.get("aiya_admin_session"))
        csrf = record.csrf_token if record is not None else None
        created_at = int(record.created_at) if record is not None else None
        last_seen = int(record.last_seen) if record is not None else None
    else:
        csrf = None
        created_at = None
        last_seen = None
    idle_expires_at = (
        datetime.fromtimestamp(
            last_seen + services.settings.admin_session_idle_seconds,
            UTC,
        )
        if last_seen is not None
        else None
    )
    absolute_expires_at = (
        datetime.fromtimestamp(
            created_at + services.settings.admin_session_absolute_seconds,
            UTC,
        )
        if created_at is not None
        else None
    )
    return AdminSessionDTO(
        subject_id=subject.id,
        username=subject.username,
        display_name=subject.display_name,
        avatar_asset_id=subject.avatar_asset_id,
        status=subject.status,
        capabilities=sorted(ctx.principal.capabilities),
        csrf_token=csrf,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
    )


def _epoch_seconds(clock: Clock) -> int:
    return int(clock.utc_now().timestamp())
