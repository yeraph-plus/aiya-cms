"""Community Markdown source validation and plain-text extraction."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from inc.kernel.errors import ErrorCategory, KernelError

_FRONTMATTER = re.compile(r"^(---|\+\+\+)\s*$")
_MDX_IMPORT_EXPORT = re.compile(r"^\s*(?:import|export)\b")
_MDX_DIRECTIVE = re.compile(r"^\s*(?:::|:[a-zA-Z][\w-]*\[)")
_MDX_EXPRESSION = re.compile(r"^\s*\{[^{}]*\}\s*$")
_PARSER = MarkdownIt("commonmark", {"html": True, "linkify": False})


def _keep_link_destination(_: str) -> bool:
    return True


cast(Any, _PARSER).validateLink = _keep_link_destination


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    source: str
    plain_text: str


def _error(code: str, message: str) -> KernelError:
    return KernelError(code=code, category=ErrorCategory.VALIDATION, message=message)


def _normalize_destination(value: str) -> str:
    normalized = value
    for _ in range(2):
        decoded = html.unescape(unquote(normalized))
        if decoded == normalized:
            break
        normalized = decoded
    return "".join(char for char in normalized if ord(char) > 0x20 and ord(char) != 0x7F)


def _validate_link(value: str) -> None:
    destination = _normalize_destination(value)
    if destination.startswith("#") or (
        destination.startswith("/") and not destination.startswith("//")
    ):
        return
    parsed = urlsplit(destination)
    if parsed.scheme.lower() not in {"https", "mailto", "tel"}:
        raise _error("community.markdown_invalid", "markdown link scheme is not allowed")
    if parsed.username is not None or parsed.password is not None:
        raise _error("community.markdown_invalid", "markdown link credentials are not allowed")


def _outside_fences(source: str) -> list[str]:
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


def _reject_extensions(source: str) -> None:
    lines = _outside_fences(source)
    meaningful = [line for line in lines if line.strip()]
    if len(meaningful) >= 2 and _FRONTMATTER.fullmatch(meaningful[0]) is not None:
        if any(_FRONTMATTER.fullmatch(line) is not None for line in meaningful[1:]):
            raise _error("community.markdown_invalid", "frontmatter is not allowed")
    if any(
        _MDX_IMPORT_EXPORT.match(line) or _MDX_DIRECTIVE.match(line) or _MDX_EXPRESSION.match(line)
        for line in lines
    ):
        raise _error("community.markdown_invalid", "MDX and directives are not allowed")


def _plain_text(tokens: list[Any]) -> str:
    parts: list[str] = []
    for token in tokens:
        if token.type in {
            "text",
            "code_inline",
            "code_block",
            "fence",
            "html_block",
            "html_inline",
        }:
            if token.type not in {"html_block", "html_inline"}:
                parts.append(token.content)
        elif token.type in {
            "softbreak",
            "hardbreak",
            "paragraph_close",
            "heading_close",
            "list_item_close",
        }:
            parts.append("\n")
        if token.children:
            parts.append(_plain_text(token.children))
    return "".join(parts)


def validate_markdown(body: str, *, max_bytes: int) -> MarkdownDocument:
    """Normalize and validate source without producing or storing HTML."""

    source = body.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in source or any(ord(char) < 0x20 and char not in {"\t", "\n"} for char in source):
        raise _error(
            "community.markdown_invalid", "markdown contains unsupported control characters"
        )
    if len(source.encode("utf-8")) > max_bytes:
        raise _error("community.body_too_large", "markdown source exceeds the byte limit")
    if not source.strip():
        raise _error("community.markdown_invalid", "markdown body is empty")
    _reject_extensions(source)
    try:
        tokens = _PARSER.parse(source)
    except Exception as exc:  # pragma: no cover - parser boundary
        raise _error("community.markdown_invalid", "markdown cannot be parsed") from exc
    for token in _walk_tokens(tokens):
        if token.type in {"html_block", "html_inline", "image"}:
            raise _error("community.markdown_invalid", "raw HTML and images are not allowed")
        if token.type == "link_open":
            destination = token.attrGet("href")
            if destination is not None:
                _validate_link(destination)
    return MarkdownDocument(source=source, plain_text=_plain_text(tokens))


def _walk_tokens(tokens: list[Any]) -> list[Any]:
    walked: list[Any] = []
    for token in tokens:
        walked.append(token)
        if token.children:
            walked.extend(_walk_tokens(token.children))
    return walked
