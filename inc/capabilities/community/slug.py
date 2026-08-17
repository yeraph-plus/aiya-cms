"""Versioned, non-reversible community discussion slugs."""

from __future__ import annotations

import re
import secrets

from slugify import slugify

_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_SUFFIX_LENGTH = 8
_STEM_MAX_LENGTH = 64


def generate_discussion_slug(title: str) -> str:
    stem = slugify(title, lowercase=True, separator="-", allow_unicode=False)
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:_STEM_MAX_LENGTH].strip("-")
    if not stem:
        stem = "discussion"
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(_SUFFIX_LENGTH))
    return f"{stem}-{suffix}"


generate_slug = generate_discussion_slug
