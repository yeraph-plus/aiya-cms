"""Password policy.

Contract source: context/spec/capabilities/identity.md §6.

The policy is versioned so parameters can be upgraded without breaking
existing hashes; stored hashes carry their own algorithm version.
"""

from __future__ import annotations

from dataclasses import dataclass

HASH_VERSION = "argon2-v1"


@dataclass(frozen=True, slots=True)
class PasswordPolicy:
    min_length: int = 8
    max_length: int = 128


def validate_password(policy: PasswordPolicy, password: str) -> None:
    if len(password) < policy.min_length:
        raise ValueError(f"password must be at least {policy.min_length} characters")
    if len(password) > policy.max_length:
        raise ValueError(f"password must be at most {policy.max_length} characters")
