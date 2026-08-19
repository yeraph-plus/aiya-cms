"""Membership subject-reference adapter."""

from __future__ import annotations

from inc.capabilities.identity import IdentityQueries


class IdentitySubjectExists:
    """Opaque subject reference resolved through the identity capability."""

    def __init__(self, *, queries: IdentityQueries) -> None:
        self._queries = queries

    async def __call__(self, subject_type: str, subject_id: str) -> bool:
        if subject_type != "identity":
            return False
        return await self._queries.get_subject(subject_id) is not None
