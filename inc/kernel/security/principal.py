"""The request subject used by kernel authorization checks."""

from __future__ import annotations

from uuid import UUID

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

_ANONYMOUS_ID = UUID(int=0)


class Principal(BaseModel):
    """Immutable-ish request principal with a capability snapshot."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    username: str = Field(min_length=1)
    roles: frozenset[str] = frozenset()
    capabilities: frozenset[str] = frozenset()
    is_system_bot: bool = False
    is_anonymous: bool = False

    @classmethod
    def anonymous(cls) -> Principal:
        return cls(
            id=_ANONYMOUS_ID,
            username="anonymous",
            is_anonymous=True,
        )

    @classmethod
    def system_bot(
        cls,
        *,
        capabilities: frozenset[str] | set[str] = frozenset(),
        username: str = "system-bot",
    ) -> Principal:
        return cls(
            id=_ANONYMOUS_ID,
            username=username,
            capabilities=frozenset(capabilities),
            is_system_bot=True,
        )


async def get_current_principal(request: Request) -> Principal:
    """Read the principal installed by auth middleware, defaulting to anonymous."""

    principal = getattr(request.state, "principal", None)
    return principal if isinstance(principal, Principal) else Principal.anonymous()
