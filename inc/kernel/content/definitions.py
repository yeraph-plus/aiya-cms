"""Declarative definitions for kernel-owned content types.

Concrete content types live in ``inc.modules`` and are compiled into the
immutable definitions consumed by the kernel.  This module deliberately has
no imports from the modules layer.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar

type ContentValidator = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class ContentField:
    """One declared data field rendered by the client and persisted as text."""

    slug: str
    title: str
    description: str = ""
    input_type: str = "text"
    required: bool = False
    constraints: Mapping[str, Any] = field(default_factory=dict)
    validator: ContentValidator | None = None


@dataclass(frozen=True, slots=True)
class ContentStatusDef:
    """A type-owned status; ``trash`` is reserved by the kernel."""

    slug: str
    is_public: bool = False


@dataclass(frozen=True, slots=True)
class ContentTransitionDef:
    """An explicitly allowed state-machine action."""

    action: str
    from_statuses: tuple[str, ...]
    to_status: str
    capability: str


@dataclass(frozen=True, slots=True)
class TaxonomyGroupDef:
    """A flat taxonomy group available to a content type."""

    slug: str
    title: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class CommentPolicy:
    """Comment behavior declared by a content type."""

    allow: bool = True
    max_depth: int = 3
    auto_approve: bool = False
    rate_limit: int = 10


@dataclass(frozen=True, slots=True)
class TrashPolicy:
    """Retention policy for the kernel-provided ``trash`` state."""

    retention_days: int = 30


class ContentType(ABC):
    """Abstract, code-owned content type declaration.

    Subclasses must provide ``type_name``, ``statuses``, ``default_status`` and
    ``fields``.  The interpreter performs all validation at application
    startup, so importing a declaration does not mutate any global registry.
    """

    type_name: ClassVar[str]
    statuses: ClassVar[tuple[ContentStatusDef, ...]]
    default_status: ClassVar[str]
    transitions: ClassVar[tuple[ContentTransitionDef, ...]] = ()
    fields: ClassVar[tuple[ContentField, ...]]
    taxonomy_groups: ClassVar[tuple[TaxonomyGroupDef, ...]] = ()
    comment_policy: ClassVar[CommentPolicy] = CommentPolicy()
    trash_policy: ClassVar[TrashPolicy] = TrashPolicy()


@dataclass(frozen=True, slots=True)
class ContentTypeDefinition:
    """Validated immutable projection of a ``ContentType`` declaration."""

    type_name: str
    statuses: tuple[ContentStatusDef, ...]
    default_status: str
    transitions: tuple[ContentTransitionDef, ...]
    fields: tuple[ContentField, ...]
    taxonomy_groups: tuple[TaxonomyGroupDef, ...]
    comment_policy: CommentPolicy
    trash_policy: TrashPolicy

    def metadata(self) -> dict[str, Any]:
        """Return safe HTTP metadata without exposing validation callbacks."""

        return {
            "type_name": self.type_name,
            "statuses": [
                {"slug": status.slug, "is_public": status.is_public} for status in self.statuses
            ],
            "default_status": self.default_status,
            "transitions": [
                {
                    "action": transition.action,
                    "from_statuses": list(transition.from_statuses),
                    "to_status": transition.to_status,
                    "capability": transition.capability,
                }
                for transition in self.transitions
            ],
            "fields": [
                {
                    "slug": field.slug,
                    "title": field.title,
                    "description": field.description,
                    "input_type": field.input_type,
                    "required": field.required,
                    "constraints": dict(field.constraints),
                }
                for field in self.fields
            ],
            "taxonomy_groups": [
                {
                    "slug": group.slug,
                    "title": group.title,
                    "description": group.description,
                }
                for group in self.taxonomy_groups
            ],
            "comment_policy": {
                "allow": self.comment_policy.allow,
                "max_depth": self.comment_policy.max_depth,
                "auto_approve": self.comment_policy.auto_approve,
                "rate_limit": self.comment_policy.rate_limit,
            },
            "trash_policy": {"retention_days": self.trash_policy.retention_days},
        }

    def with_immutable_constraints(self) -> ContentTypeDefinition:
        """Copy field constraints into read-only mappings for registry storage."""

        fields = tuple(
            ContentField(
                slug=field.slug,
                title=field.title,
                description=field.description,
                input_type=field.input_type,
                required=field.required,
                constraints=MappingProxyType(dict(field.constraints)),
                validator=field.validator,
            )
            for field in self.fields
        )
        return ContentTypeDefinition(
            type_name=self.type_name,
            statuses=self.statuses,
            default_status=self.default_status,
            transitions=self.transitions,
            fields=fields,
            taxonomy_groups=self.taxonomy_groups,
            comment_policy=self.comment_policy,
            trash_policy=self.trash_policy,
        )
