"""Identifier normalization.

Contract source: context/spec/capabilities/identity.md §6.

Usernames and emails keep a display value and a unique normalized value
(NFKC + casefold). No provider-specific email tricks (Gmail dot/plus) are
implemented.
"""

from __future__ import annotations

import unicodedata


def normalize_email(value: str) -> str:
    """Unique normalized email: NFKC + casefold, stripped."""

    return unicodedata.normalize("NFKC", value).strip().casefold()


def normalize_username(value: str) -> str:
    """Unique normalized username: NFKC + casefold, stripped."""

    return unicodedata.normalize("NFKC", value).strip().casefold()
