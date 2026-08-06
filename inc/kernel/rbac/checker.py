"""Capability checks and FastAPI dependency factory."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from fastapi import Depends, Request

from inc.kernel.errors import AppError
from inc.kernel.security import Principal, get_current_principal

from .errors import RBAC_001
from .registry import capability_registry
from .schemas import PolicyContext

ContextLoader = Callable[..., PolicyContext | None | Awaitable[PolicyContext | None]]


class CapabilityChecker:
    """Pure in-memory checker over a Principal capability snapshot."""

    def check(
        self,
        principal: Principal,
        alias: str,
        context: PolicyContext | None = None,
    ) -> bool:
        definition = capability_registry.get(alias)
        if principal.is_anonymous:
            return False
        if principal.is_system_bot:
            return True

        has_alias = alias in principal.capabilities
        # Only the matching ``*_any`` capability may bypass the corresponding
        # owner policy. Update and delete are intentionally separate powers.
        domain, _, operation = alias.partition(":")
        bypass_alias: str | None = None
        if operation == "update_own":
            bypass_alias = f"{domain}:update_any"
        elif operation == "delete_own":
            bypass_alias = f"{domain}:delete_any"
        elif alias == "content:publish":
            bypass_alias = "content:update_any"
        if not has_alias and bypass_alias not in principal.capabilities:
            return False
        if bypass_alias is not None and bypass_alias in principal.capabilities:
            return True
        return definition.policy is None or definition.policy(principal, context)

    def require(
        self,
        principal: Principal,
        alias: str,
        context: PolicyContext | None = None,
    ) -> Principal:
        if not self.check(principal, alias, context):
            raise AppError(RBAC_001, detail={"alias": alias})
        return principal


_DEFAULT_CHECKER = CapabilityChecker()
_PRINCIPAL_DEPENDENCY = Depends(get_current_principal)


def require_capability(
    alias: str,
    context_loader: ContextLoader | None = None,
    *,
    checker: CapabilityChecker | None = None,
) -> Callable[..., Awaitable[Principal]]:
    """Build a FastAPI dependency that returns the authorised Principal."""

    capability_registry.get(alias)  # construction-time fail-fast for unknown aliases
    active_checker = checker or _DEFAULT_CHECKER

    async def dependency(
        request: Request,
        principal: Principal = _PRINCIPAL_DEPENDENCY,
    ) -> Principal:
        auth_error = getattr(request.state, "auth_error", None)
        if isinstance(auth_error, AppError):
            raise auth_error
        context: PolicyContext | None = None
        if context_loader is not None:
            parameters = inspect.signature(context_loader).parameters
            if len(parameters) == 0:
                context = context_loader()  # type: ignore[assignment]
            elif len(parameters) >= 2:
                context = context_loader(request, principal)  # type: ignore[assignment]
            else:
                context = context_loader(request)  # type: ignore[assignment]
            if inspect.isawaitable(context):
                context = await context
        return active_checker.require(principal, alias, context)

    return dependency


def require_any_capability(
    aliases: tuple[str, ...] | list[str], *, checker: CapabilityChecker | None = None
) -> Callable[..., Awaitable[Principal]]:
    """Build a dependency that accepts any one of the registered capabilities."""

    normalized = tuple(aliases)
    if not normalized:
        raise ValueError("at least one capability is required")
    for alias in normalized:
        capability_registry.get(alias)
    active_checker = checker or _DEFAULT_CHECKER

    async def dependency(
        request: Request,
        principal: Principal = _PRINCIPAL_DEPENDENCY,
    ) -> Principal:
        auth_error = getattr(request.state, "auth_error", None)
        if isinstance(auth_error, AppError):
            raise auth_error
        if not any(active_checker.check(principal, alias) for alias in normalized):
            raise AppError(RBAC_001, detail={"aliases": list(normalized)})
        return principal

    return dependency


def check_capability(
    principal: Principal, alias: str, context: PolicyContext | None = None
) -> bool:
    """Convenience wrapper used by non-HTTP code."""

    return _DEFAULT_CHECKER.check(principal, alias, context)
