"""Markdown source validation and public-slug generation.

The content capability persists normalized Markdown source only.  This module
never renders HTML: Astro owns rendering and sanitization at the user-site
boundary.
"""

from __future__ import annotations

import html
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from slugify import slugify

from inc.capabilities.content.types import ContentTypeSpec
from inc.kernel.errors import ErrorCategory, KernelError

_ASSET_REFERENCE = re.compile(r"^asset:([0-9a-fA-F-]{36})$")
_FRONTMATTER_DELIMITER = re.compile(r"^(---|\+\+\+)\s*$")
_MDX_IMPORT_EXPORT = re.compile(r"^\s*(?:import|export)\b")
_MDX_DIRECTIVE = re.compile(r"^\s*(?:::|:[a-zA-Z][\w-]*\[)")
_MDX_EXPRESSION = re.compile(r"^\s*\{[^{}]*\}\s*$")
_SLUG_SUFFIX_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_SLUG_SUFFIX_LENGTH = 8
_SLUG_STEM_MAX_LENGTH = 64
_PARSER = MarkdownIt("commonmark", {"html": True, "linkify": False})


def _parse_all_link_destinations(_: str) -> bool:
    """Keep unsafe links as tokens so the contract validator can reject them."""

    return True


cast(Any, _PARSER).validateLink = _parse_all_link_destinations


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    """Validated source and opaque asset references extracted from it."""

    source: str | None
    asset_ids: tuple[uuid.UUID, ...]


def _validation(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


def _normalize_destination(value: str) -> str:
    normalized = value
    for _ in range(2):
        decoded = html.unescape(unquote(normalized))
        if decoded == normalized:
            break
        normalized = decoded
    return "".join(char for char in normalized if ord(char) > 0x20 and ord(char) != 0x7F)


def _validate_link_destination(value: str) -> None:
    destination = _normalize_destination(value)
    if destination.startswith("#"):
        return
    if destination.startswith("/") and not destination.startswith("//"):
        return

    parsed = urlsplit(destination)
    scheme = parsed.scheme.lower()
    if scheme not in {"https", "mailto", "tel"}:
        raise _validation(
            "content.markdown_link_not_allowed", "markdown link scheme is not allowed"
        )
    if parsed.username is not None or parsed.password is not None:
        raise _validation(
            "content.markdown_link_not_allowed", "markdown link credentials are not allowed"
        )


def _asset_id(value: str) -> uuid.UUID:
    match = _ASSET_REFERENCE.fullmatch(value)
    if match is None:
        raise _validation(
            "content.markdown_asset_invalid", "markdown images must use an asset UUID reference"
        )
    try:
        return uuid.UUID(match.group(1))
    except ValueError as exc:
        raise _validation(
            "content.markdown_asset_invalid", "markdown asset UUID is invalid"
        ) from exc


def _lines_outside_fences(source: str) -> list[str]:
    lines: list[str] = []
    fence: str | None = None
    for line in source.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker is not None:
            current = marker.group(1)[0]
            if fence is None:
                fence = current
            elif fence == current:
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return lines


def _reject_disallowed_extensions(source: str) -> None:
    lines = _lines_outside_fences(source)
    meaningful = [line for line in lines if line.strip()]
    if len(meaningful) >= 2:
        delimiter = _FRONTMATTER_DELIMITER.fullmatch(meaningful[0])
        if delimiter is not None and any(
            _FRONTMATTER_DELIMITER.fullmatch(line) and line == meaningful[0]
            for line in meaningful[1:]
        ):
            raise _validation("content.markdown_feature_not_allowed", "frontmatter is not allowed")
    for line in lines:
        if (
            _MDX_IMPORT_EXPORT.match(line)
            or _MDX_DIRECTIVE.match(line)
            or _MDX_EXPRESSION.match(line)
        ):
            raise _validation(
                "content.markdown_feature_not_allowed", "MDX or directives are not allowed"
            )


def _walk_tokens(tokens: list[Any]) -> list[Any]:
    walked: list[Any] = []
    for token in tokens:
        walked.append(token)
        walked.extend(token.children or [])
    return walked


def validate_markdown(spec: ContentTypeSpec, body: str | None) -> MarkdownDocument:
    """Normalize and validate a Markdown source without rendering it."""

    if body is None:
        return MarkdownDocument(source=None, asset_ids=())
    source = body.replace("\r\n", "\n").replace("\r", "\n")
    if any(ord(char) < 0x20 and char not in {"\t", "\n"} for char in source):
        raise _validation(
            "content.markdown_invalid", "markdown contains unsupported control characters"
        )
    if spec.body_max_bytes is not None and len(source.encode("utf-8")) > spec.body_max_bytes:
        raise _validation("content.body_too_large", "markdown source exceeds the byte limit")
    _reject_disallowed_extensions(source)
    try:
        tokens = _PARSER.parse(source)
    except Exception as exc:  # pragma: no cover - defensive parser boundary
        raise _validation("content.markdown_invalid", "markdown cannot be parsed") from exc

    asset_ids: list[uuid.UUID] = []
    for token in _walk_tokens(tokens):
        if token.type in {"html_block", "html_inline"}:
            raise _validation("content.markdown_feature_not_allowed", "raw HTML is not allowed")
        if token.type == "link_open":
            destination = token.attrGet("href")
            if destination is not None:
                _validate_link_destination(destination)
        if token.type == "image":
            source_url = token.attrGet("src")
            if source_url is None:
                raise _validation(
                    "content.markdown_asset_invalid", "markdown image source is missing"
                )
            asset_ids.append(_asset_id(source_url))
    return MarkdownDocument(source=source, asset_ids=tuple(dict.fromkeys(asset_ids)))


def generate_slug(spec: ContentTypeSpec, title: str) -> str:
    """Create one non-reversible public slug candidate for a content title."""

    stem = slugify(title, lowercase=True, separator="-", allow_unicode=False)
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:_SLUG_STEM_MAX_LENGTH].strip("-")
    if not stem:
        stem = spec.type_name if spec.type_name in {"post", "page"} else "content"
    suffix = "".join(secrets.choice(_SLUG_SUFFIX_ALPHABET) for _ in range(_SLUG_SUFFIX_LENGTH))
    return f"{stem}-{suffix}"
