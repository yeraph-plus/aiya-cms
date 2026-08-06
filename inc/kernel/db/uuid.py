"""UUIDv7 generation via uuid-utils, normalized to the stdlib type.

uuid-utils returns its own C-backed ``uuid_utils.UUID``, which asyncpg cannot
encode for native UUID columns. We re-wrap the int so the value is a plain
:class:`uuid.UUID`; the version/variant bits live in the int, so nothing is
lost.
"""

import uuid

import uuid_utils

__all__ = ["new_uuid7"]


def new_uuid7() -> uuid.UUID:
    """Return a monotonic, time-ordered UUIDv7 as a standard :class:`uuid.UUID`."""
    return uuid.UUID(int=uuid_utils.uuid7().int)
