"""ORM -> DTO mappers (capability-internal)."""

from __future__ import annotations

from inc.capabilities.identity.models import IdentityUser
from inc.capabilities.identity.schemas import SubjectDTO


def to_subject(user: IdentityUser) -> SubjectDTO:
    return SubjectDTO(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        email=user.email_display,
        email_verified=user.email_verified_at is not None,
        status=user.status,
        avatar_asset_id=str(user.avatar_asset_id) if user.avatar_asset_id else None,
        created_at=user.created_at,
    )
