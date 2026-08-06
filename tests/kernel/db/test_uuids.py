"""Red tests locking the UUIDv7 primitive (M1.2 db).

Contract source: context/spec/kernel.md
"""

import uuid

from inc.kernel.db import new_uuid7


def test_new_uuid7_is_standard_uuid_version_7() -> None:
    value = new_uuid7()

    assert isinstance(value, uuid.UUID)
    assert value.version == 7


def test_new_uuid7_is_monotonic_within_same_millisecond() -> None:
    uuids = [new_uuid7() for _ in range(5000)]

    assert uuids == sorted(uuids)
    assert len(set(uuids)) == len(uuids)
