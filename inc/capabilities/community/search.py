"""Pure search normalization and Markdown projection helpers."""

from __future__ import annotations

import re
import unicodedata

from inc.capabilities.community.markdown import validate_markdown
from inc.kernel.errors import ErrorCategory, KernelError

SEARCH_PROFILE = "community_trigram_v1"


def _invalid(message: str) -> KernelError:
    return KernelError(
        code="community.search_query_invalid",
        category=ErrorCategory.VALIDATION,
        message=message,
    )


def normalize_search_text(value: str, *, query: bool = False) -> str:
    """Normalize both indexed text and queries with one profile function."""

    if "\x00" in value or any(
        unicodedata.category(char) == "Cc" and (query or char not in {"\t", "\n", "\r"})
        for char in value
    ):
        raise _invalid("search text contains a control character")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = " ".join(normalized.split())
    if query:
        if not normalized:
            raise _invalid("search query is empty")
        if len(normalized) < 1 or len(normalized) > 128:
            raise _invalid("search query must contain 1 to 128 Unicode scalars")
        if len(normalized.split()) > 8:
            raise _invalid("search query contains more than 8 tokens")
    return normalized


def normalize_query(value: str) -> tuple[str, tuple[str, ...]]:
    normalized = normalize_search_text(value, query=True)
    return normalized, tuple(normalized.split())


def markdown_search_text(body: str, *, max_bytes: int = 262144) -> str:
    document = validate_markdown(body, max_bytes=max_bytes)
    return normalize_search_text(document.plain_text)


def title_search_text(title: str) -> str:
    return normalize_search_text(title)


def contains_query(normalized_text: str, token: str) -> bool:
    return token in normalized_text


def rank_text(normalized_text: str, query: str) -> float:
    """Deterministic local rank used by non-PostgreSQL callers/tests."""

    if normalized_text == query:
        return 3.0
    if normalized_text.startswith(query):
        return 2.5
    if query in normalized_text:
        return 2.0
    return 1.0 if all(token in normalized_text for token in query.split()) else 0.0


def escape_like(value: str) -> str:
    return re.sub(r"([\\%_])", r"\\\1", value)
