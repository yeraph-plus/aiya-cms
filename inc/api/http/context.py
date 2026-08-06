"""Request-scoped AppContext and bearer-token authentication.

Contract source: context/spec/composition.md §8, http-openapi.md §5.

Bearer tokens are OIDC access tokens issued by this system: RS256
verified against the issuer's current JWKS, with issuer/audience/expiry
checks. The access capability is the final authorization boundary; the
capability set comes from access grants, never from token claims.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from inc.api.container import Services
from inc.capabilities.access.schemas import Principal
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time import Clock

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(message: str) -> KernelError:
    return KernelError(
        code="api.unauthorized", category=ErrorCategory.UNAUTHORIZED, message=message
    )


@dataclass(frozen=True, slots=True)
class AppContext:
    """Request-scoped values; never a service locator."""

    principal: Principal
    request_id: str
    trace_id: str
    uow_factory: UoWFactory
    clock: Clock


class BearerVerifier:
    """Validates access tokens against the issuer's current keys."""

    def __init__(
        self,
        *,
        services: Services,
        issuer: str,
        api_audience: str,
    ) -> None:
        self._services = services
        self._issuer = issuer
        self._api_audience = api_audience

    async def verify(
        self,
        credentials: HTTPAuthorizationCredentials | None,
        request: Request,
    ) -> AppContext:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized("missing bearer token")
        payload = await self._decode(credentials.credentials)
        subject_id = str(payload.get("sub", ""))
        if not subject_id:
            raise _unauthorized("access token carries no subject")

        async with self._services.uow_factory():
            subject = await self._services.identity_queries.get_subject(subject_id)
        if subject is None:
            raise _unauthorized("subject no longer exists")
        if subject.status != "active":
            raise _unauthorized("subject is not active")

        principal = Principal(
            subject_id=subject_id,
            status="active",
            auth_method="bearer",
            client_id=payload.get("client_id"),
        )
        capabilities = await self._services.authorize.capabilities_of(principal)
        principal = Principal(
            subject_id=subject_id,
            status="active",
            auth_method="bearer",
            client_id=payload.get("client_id"),
            capabilities=capabilities,
        )
        request_id = getattr(request.state, "request_id", "unknown")
        return AppContext(
            principal=principal,
            request_id=request_id,
            trace_id=request_id,
            uow_factory=self._services.uow_factory,
            clock=self._services.clock,
        )

    async def _decode(self, token: str) -> dict[str, Any]:
        from jwt.algorithms import RSAAlgorithm

        jwks = await self._services.keys.public_jwks()
        for key in jwks.get("keys", []):
            kid = key.get("kid")
            if kid is None:
                continue
            try:
                public_key: Any = RSAAlgorithm.from_jwk(key)
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    issuer=self._issuer,
                    audience=self._api_audience,
                    options={"require": ["exp", "iat"]},
                )
                return payload
            except jwt.PyJWTError:
                continue
        raise _unauthorized("invalid or expired access token")


RequireCapability = Callable[[str], Callable[..., Any]]


def make_require_capability(*, verifier: BearerVerifier) -> RequireCapability:
    """Dependency factory bound to one app's verifier."""

    async def _resolve(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
        request: Request = None,  # type: ignore[assignment]
    ) -> AppContext:
        return await verifier.verify(credentials, request)

    def require_capability(permission_key: str) -> Callable[..., Any]:
        async def _dependency(
            ctx: AppContext = Depends(_resolve),
        ) -> AppContext:
            if permission_key not in ctx.principal.capabilities:
                raise KernelError(
                    code="api.forbidden",
                    category=ErrorCategory.FORBIDDEN,
                    message=f"requires capability {permission_key}",
                )
            return ctx

        return _dependency

    return require_capability
