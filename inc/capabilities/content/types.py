"""Content type declarations and registry.

Contract source: context/spec/capabilities/content.md §2.

ContentTypeSpec is an immutable code declaration registered by features
(post, page, ...). The capability validates and executes it; the registry
fails fast on duplicate types, unknown states, transitions without start
or end points, schema conflicts or unregistered permission keys.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from inc.kernel.errors import ErrorCategory, KernelError

STANDARD_STATES = ("draft", "pending", "rejected", "scheduled", "published", "archived")

DEFAULT_TRANSITIONS: tuple[tuple[str, str], ...] = (
    ("draft", "pending"),
    ("draft", "scheduled"),
    ("draft", "published"),
    ("pending", "draft"),
    ("pending", "rejected"),
    ("pending", "scheduled"),
    ("pending", "published"),
    ("rejected", "draft"),
    ("scheduled", "draft"),
    ("scheduled", "published"),
    ("published", "archived"),
    ("archived", "draft"),
)

_TYPE_KEY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ContentTypeSpec:
    """Immutable declaration of a content type (registered by a feature)."""

    __slots__ = (
        "type_name",
        "version",
        "display_name",
        "data_schema",
        "data_schema_version",
        "allowed_states",
        "default_state",
        "transitions",
        "allows_schedule",
        "allows_pin",
        "allows_owner",
        "allows_references",
        "allows_incoming_references",
        "slug_pattern",
        "title_max_length",
        "body_max_length",
        "excerpt_max_length",
        "required_access_keys",
        "public_fields",
        "sort_options",
    )

    def __init__(
        self,
        *,
        type_name: str,
        version: str,
        display_name: str,
        data_schema: type[BaseModel],
        data_schema_version: str,
        allowed_states: tuple[str, ...],
        default_state: str,
        transitions: tuple[tuple[str, str], ...] = DEFAULT_TRANSITIONS,
        allows_schedule: bool = False,
        allows_pin: bool = False,
        allows_owner: bool = False,
        allows_references: bool = False,
        allows_incoming_references: bool = True,
        slug_pattern: str = r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        title_max_length: int = 200,
        body_max_length: int | None = None,
        excerpt_max_length: int | None = None,
        required_access_keys: tuple[str, ...] = (),
        public_fields: tuple[str, ...] = (
            "id",
            "type_name",
            "slug",
            "title",
            "excerpt",
            "status",
            "published_at",
            "updated_at",
        ),
        sort_options: tuple[str, ...] = (
            "published_at",
            "id",
            "title",
            "view_count",
            "like_count",
            "rating_sum",
            "rating_count",
            "rating_average",
        ),
    ) -> None:
        if not _TYPE_KEY.match(type_name):
            raise ValueError(f"invalid type_name {type_name!r}")
        if not version:
            raise ValueError(f"type {type_name} requires a version")
        if not isinstance(data_schema, type) or not issubclass(data_schema, BaseModel):
            raise ValueError(f"type {type_name} requires a Pydantic data schema")
        unknown = set(allowed_states) - set(STANDARD_STATES)
        if unknown:
            raise ValueError(f"type {type_name} declares unknown states {sorted(unknown)}")
        if not allowed_states:
            raise ValueError(f"type {type_name} requires at least one state")
        if default_state not in allowed_states:
            raise ValueError(f"default_state {default_state!r} not in allowed_states")
        states = set(allowed_states)
        for src, dst in transitions:
            if src not in states or dst not in states:
                raise ValueError(
                    f"type {type_name} transition {src} -> {dst} has unknown start/end"
                )
        outgoing = {t[0] for t in transitions}
        incoming = {t[1] for t in transitions}
        dead = states - outgoing
        unreachable = states - incoming
        if dead:
            raise ValueError(
                f"type {type_name} states without an outgoing transition: {sorted(dead)}"
            )
        if unreachable:
            raise ValueError(
                f"type {type_name} states without an incoming transition: {sorted(unreachable)}"
            )
        if (
            title_max_length < 1
            or (body_max_length is not None and body_max_length < 1)
            or (excerpt_max_length is not None and excerpt_max_length < 1)
        ):
            raise ValueError(f"type {type_name} declares invalid length constraints")
        if not slug_pattern:
            raise ValueError(f"type {type_name} requires a slug pattern")
        re.compile(slug_pattern)
        for key in required_access_keys:
            if not re.match(r"^[a-z0-9]+(\.[a-z0-9_]+)+$", key):
                raise ValueError(f"type {type_name} declares invalid access key {key!r}")

        self.type_name = type_name
        self.version = version
        self.display_name = display_name
        self.data_schema = data_schema
        self.data_schema_version = data_schema_version
        self.allowed_states = allowed_states
        self.default_state = default_state
        self.transitions = transitions
        self.allows_schedule = allows_schedule
        self.allows_pin = allows_pin
        self.allows_owner = allows_owner
        self.allows_references = allows_references
        self.allows_incoming_references = allows_incoming_references
        self.slug_pattern = slug_pattern
        self.title_max_length = title_max_length
        self.body_max_length = body_max_length
        self.excerpt_max_length = excerpt_max_length
        self.required_access_keys = required_access_keys
        self.public_fields = public_fields
        self.sort_options = sort_options

    def can_transition(self, current: str, target: str) -> bool:
        return (current, target) in self.transitions


class ContentTypeRegistry:
    """type_name -> ContentTypeSpec; frozen after boot."""

    def __init__(self, *, permission_keys: Any = None) -> None:
        self._types: dict[str, ContentTypeSpec] = {}
        self._frozen = False
        self._permission_keys = permission_keys

    def register(self, spec: ContentTypeSpec) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=f"content type registry is frozen; cannot register {spec.type_name}",
            )
        if spec.type_name in self._types:
            raise KernelError(
                code="content.duplicate_type",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate content type {spec.type_name}",
            )
        if self._permission_keys is not None:
            for key in spec.required_access_keys:
                self._permission_keys.require(key)
        self._types[spec.type_name] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, type_name: str) -> ContentTypeSpec:
        spec = self._types.get(type_name)
        if spec is None:
            raise KernelError(
                code="content.unknown_type",
                category=ErrorCategory.INTERNAL,
                message=f"content type {type_name!r} is not registered",
            )
        return spec

    def specs(self) -> tuple[ContentTypeSpec, ...]:
        return tuple(self._types.values())
