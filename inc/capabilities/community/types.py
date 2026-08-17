"""Discussion template declarations and registry."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import ErrorCategory, KernelError

COMMUNITY_DISCUSSION_STATES = ("draft", "pending", "published", "hidden", "archived")
COMMUNITY_POST_STATES = ("pending", "published", "hidden", "deleted")
COMMUNITY_DISCUSSION_TRANSITIONS: tuple[tuple[str, str], ...] = (
    ("draft", "pending"),
    ("draft", "published"),
    ("pending", "draft"),
    ("pending", "published"),
    ("pending", "hidden"),
    ("published", "hidden"),
    ("published", "archived"),
    ("hidden", "published"),
    ("hidden", "archived"),
    ("archived", "published"),
)
COMMUNITY_POST_TRANSITIONS: tuple[tuple[str, str], ...] = (
    ("pending", "published"),
    ("pending", "hidden"),
    ("published", "hidden"),
    ("hidden", "published"),
    ("pending", "deleted"),
    ("published", "deleted"),
    ("hidden", "deleted"),
)

_KEY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_PERMISSION = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")


class EmptyDiscussionData(BaseModel):
    """The first general template has no required JSON fields."""

    model_config = ConfigDict(extra="forbid")


class EmptyPostData(BaseModel):
    """The first general template has no required post JSON fields."""

    model_config = ConfigDict(extra="forbid")


class DiscussionTemplateSpec:
    """Immutable declaration for one community discussion template."""

    __slots__ = (
        "template_key",
        "version",
        "display_name",
        "discussion_data_schema",
        "discussion_data_schema_version",
        "post_data_schema",
        "post_data_schema_version",
        "allowed_discussion_states",
        "default_discussion_state",
        "discussion_transitions",
        "allowed_post_states",
        "post_transitions",
        "default_post_state",
        "title_min_length",
        "title_max_length",
        "body_format",
        "body_profile",
        "body_max_bytes",
        "reply_body_max_bytes",
        "discussion_moderation",
        "reply_moderation",
        "min_primary_tags",
        "max_primary_tags",
        "min_secondary_tags",
        "max_secondary_tags",
        "create_access_key",
        "reply_access_key",
        "edit_access_key",
        "moderate_access_key",
        "lock_access_key",
        "archive_access_key",
        "tags_access_key",
        "required_access_keys",
        "public_fields",
        "_initialized",
    )

    def __init__(
        self,
        *,
        template_key: str,
        version: str,
        display_name: str,
        discussion_data_schema: type[BaseModel],
        discussion_data_schema_version: str,
        post_data_schema: type[BaseModel],
        post_data_schema_version: str,
        allowed_discussion_states: tuple[str, ...] = COMMUNITY_DISCUSSION_STATES,
        default_discussion_state: str = "draft",
        discussion_transitions: tuple[tuple[str, str], ...] = COMMUNITY_DISCUSSION_TRANSITIONS,
        allowed_post_states: tuple[str, ...] = COMMUNITY_POST_STATES,
        post_transitions: tuple[tuple[str, str], ...] = COMMUNITY_POST_TRANSITIONS,
        default_post_state: str = "pending",
        title_min_length: int = 1,
        title_max_length: int = 200,
        body_format: str = "markdown",
        body_profile: str = "gfm-v1",
        body_max_bytes: int = 262144,
        reply_body_max_bytes: int = 262144,
        discussion_moderation: str = "direct",
        reply_moderation: str = "direct",
        min_primary_tags: int = 1,
        max_primary_tags: int = 1,
        min_secondary_tags: int = 0,
        max_secondary_tags: int = 5,
        create_access_key: str = "community.discussions.create",
        reply_access_key: str = "community.discussions.reply",
        edit_access_key: str = "community.discussions.edit_own",
        moderate_access_key: str = "community.discussions.moderate",
        lock_access_key: str = "community.discussions.lock",
        archive_access_key: str = "community.discussions.archive",
        tags_access_key: str = "community.tags.manage",
        required_access_keys: tuple[str, ...] = (),
        public_fields: tuple[str, ...] = (),
    ) -> None:
        object.__setattr__(self, "_initialized", False)
        if not _KEY.fullmatch(template_key):
            raise ValueError(f"invalid template_key {template_key!r}")
        if not version:
            raise ValueError(f"template {template_key} requires a version")
        for schema_name, schema in (
            ("discussion_data_schema", discussion_data_schema),
            ("post_data_schema", post_data_schema),
        ):
            if not isinstance(schema, type) or not issubclass(schema, BaseModel):
                raise ValueError(f"{template_key} requires a Pydantic {schema_name}")
        self._validate_states(
            template_key,
            allowed_discussion_states,
            default_discussion_state,
            discussion_transitions,
            set(COMMUNITY_DISCUSSION_STATES),
            set(),
        )
        self._validate_states(
            template_key,
            allowed_post_states,
            default_post_state,
            post_transitions,
            set(COMMUNITY_POST_STATES),
            {"deleted"},
        )
        if title_min_length < 1 or title_max_length < title_min_length:
            raise ValueError(f"template {template_key} declares invalid title limits")
        if body_format != "markdown" or body_profile != "gfm-v1":
            raise ValueError(f"template {template_key} must use markdown/gfm-v1")
        if body_max_bytes < 1 or reply_body_max_bytes < 1:
            raise ValueError(f"template {template_key} declares invalid body limits")
        if discussion_moderation not in {"direct", "pending"}:
            raise ValueError(f"template {template_key} declares invalid discussion moderation")
        if reply_moderation not in {"direct", "pending"}:
            raise ValueError(f"template {template_key} declares invalid reply moderation")
        if (
            min_primary_tags < 0
            or max_primary_tags < min_primary_tags
            or min_secondary_tags < 0
            or max_secondary_tags < min_secondary_tags
        ):
            raise ValueError(f"template {template_key} declares invalid tag limits")
        keys = (
            create_access_key,
            reply_access_key,
            edit_access_key,
            moderate_access_key,
            lock_access_key,
            archive_access_key,
            tags_access_key,
            *required_access_keys,
        )
        if any(not _PERMISSION.fullmatch(key) for key in keys):
            raise ValueError(f"template {template_key} declares an invalid access key")

        self.template_key = template_key
        self.version = version
        self.display_name = display_name
        self.discussion_data_schema = discussion_data_schema
        self.discussion_data_schema_version = discussion_data_schema_version
        self.post_data_schema = post_data_schema
        self.post_data_schema_version = post_data_schema_version
        self.allowed_discussion_states = allowed_discussion_states
        self.default_discussion_state = default_discussion_state
        self.discussion_transitions = discussion_transitions
        self.allowed_post_states = allowed_post_states
        self.post_transitions = post_transitions
        self.default_post_state = default_post_state
        self.title_min_length = title_min_length
        self.title_max_length = title_max_length
        self.body_format = body_format
        self.body_profile = body_profile
        self.body_max_bytes = body_max_bytes
        self.reply_body_max_bytes = reply_body_max_bytes
        self.discussion_moderation = discussion_moderation
        self.reply_moderation = reply_moderation
        self.min_primary_tags = min_primary_tags
        self.max_primary_tags = max_primary_tags
        self.min_secondary_tags = min_secondary_tags
        self.max_secondary_tags = max_secondary_tags
        self.create_access_key = create_access_key
        self.reply_access_key = reply_access_key
        self.edit_access_key = edit_access_key
        self.moderate_access_key = moderate_access_key
        self.lock_access_key = lock_access_key
        self.archive_access_key = archive_access_key
        self.tags_access_key = tags_access_key
        self.required_access_keys = tuple(dict.fromkeys(keys))
        self.public_fields = public_fields
        object.__setattr__(self, "_initialized", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_initialized", False):
            raise AttributeError("DiscussionTemplateSpec is immutable")
        object.__setattr__(self, name, value)

    @staticmethod
    def _validate_states(
        template_key: str,
        states: tuple[str, ...],
        default: str,
        transitions: tuple[tuple[str, str], ...],
        known_states: set[str],
        terminal_states: set[str],
    ) -> None:
        known = set(states)
        unknown = known - known_states
        if unknown:
            raise ValueError(f"template {template_key} declares unknown states {sorted(unknown)}")
        if not states or default not in known:
            raise ValueError(f"template {template_key} has an invalid default state")
        for source, target in transitions:
            if source not in known or target not in known:
                raise ValueError(
                    f"template {template_key} transition {source} -> {target} has unknown state"
                )
        if any(source == target for source, target in transitions):
            raise ValueError(f"template {template_key} cannot declare self transitions")
        dead = known - {source for source, _ in transitions} - terminal_states
        if dead:
            raise ValueError(
                f"template {template_key} states without an outgoing transition: {sorted(dead)}"
            )
        unreachable = known - {target for _, target in transitions} - {default}
        if unreachable:
            raise ValueError(
                "template "
                f"{template_key} states without an incoming transition: {sorted(unreachable)}"
            )

    def can_discussion_transition(self, source: str, target: str) -> bool:
        return (source, target) in self.discussion_transitions

    def can_post_transition(self, source: str, target: str) -> bool:
        return (source, target) in self.post_transitions

    def initial_discussion_status(self, permissions: frozenset[str]) -> str:
        if self.discussion_moderation == "direct" and self.create_access_key in permissions:
            return "published"
        return "pending"

    def initial_post_status(self, permissions: frozenset[str]) -> str:
        if self.reply_moderation == "direct" and self.reply_access_key in permissions:
            return "published"
        return "pending"

    def initial_first_post_status(self, permissions: frozenset[str]) -> str:
        if self.discussion_moderation == "direct" and self.create_access_key in permissions:
            return "published"
        return "pending"

    def validate_discussion_data(self, value: dict[str, Any]) -> dict[str, Any]:
        return self.discussion_data_schema.model_validate(value).model_dump(mode="json")

    def validate_post_data(self, value: dict[str, Any]) -> dict[str, Any]:
        return self.post_data_schema.model_validate(value).model_dump(mode="json")

    def public_data(self, value: dict[str, Any]) -> dict[str, Any]:
        """Return only data fields explicitly allowed by the template."""

        return {key: value[key] for key in self.public_fields if key in value}


class DiscussionTemplateRegistry:
    """Template registry frozen by the composition root."""

    def __init__(self, *, permission_keys: Any = None) -> None:
        self._templates: dict[str, DiscussionTemplateSpec] = {}
        self._permission_keys = permission_keys
        self._frozen = False

    def register(self, spec: DiscussionTemplateSpec) -> None:
        if self._frozen:
            raise KernelError(
                code="kernel.registry_frozen",
                category=ErrorCategory.INTERNAL,
                message=(
                    f"community template registry is frozen; cannot register {spec.template_key}"
                ),
            )
        if spec.template_key in self._templates:
            raise KernelError(
                code="community.duplicate_template",
                category=ErrorCategory.INTERNAL,
                message=f"duplicate community template {spec.template_key}",
            )
        if self._permission_keys is not None:
            for key in spec.required_access_keys:
                self._permission_keys.require(key)
        self._templates[spec.template_key] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, template_key: str) -> DiscussionTemplateSpec:
        spec = self._templates.get(template_key)
        if spec is None:
            raise KernelError(
                code="community.unknown_template",
                category=ErrorCategory.INTERNAL,
                message=f"community template {template_key!r} is not registered",
            )
        return spec

    def specs(self) -> tuple[DiscussionTemplateSpec, ...]:
        return tuple(self._templates.values())


GENERAL_DISCUSSION_TEMPLATE = DiscussionTemplateSpec(
    template_key="general",
    version="1",
    display_name="General discussion",
    discussion_data_schema=EmptyDiscussionData,
    discussion_data_schema_version="1",
    post_data_schema=EmptyPostData,
    post_data_schema_version="1",
    default_discussion_state="draft",
    default_post_state="pending",
    discussion_moderation="direct",
    reply_moderation="direct",
    min_primary_tags=1,
    max_primary_tags=1,
    min_secondary_tags=0,
    max_secondary_tags=5,
)
