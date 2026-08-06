"""Compile content declarations and validate their JSONB data values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from .definitions import (
    CommentPolicy,
    ContentField,
    ContentStatusDef,
    ContentTransitionDef,
    ContentType,
    ContentTypeDefinition,
    TaxonomyGroupDef,
    TrashPolicy,
)
from .schemas import ContentDataValues

_SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_TYPE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_INPUT_TYPES = {
    "text",
    "textarea",
    "str",
    "string",
    "bool",
    "boolean",
    "number",
    "num",
    "integer",
    "url",
    "email",
    "date",
    "datetime",
}


class ContentTypeInterpreter:
    """Single validation boundary for declarations and content data."""

    def compile(self, declaration: type[ContentType]) -> ContentTypeDefinition:
        if not isinstance(declaration, type) or not issubclass(declaration, ContentType):
            raise TypeError("content declaration must inherit ContentType")

        type_name = self._required_class_string(declaration, "type_name")
        if not _TYPE_NAME.fullmatch(type_name):
            raise ValueError("type_name must be lowercase slug-like text")

        statuses = self._statuses(declaration)
        status_slugs = [status.slug for status in statuses]
        self._unique(status_slugs, "status")
        if "trash" in status_slugs:
            raise ValueError("status slug 'trash' is reserved by the kernel")

        default_status = self._required_class_string(declaration, "default_status")
        if default_status not in status_slugs:
            raise ValueError("default_status must reference a declared status")

        transitions = self._transitions(declaration)
        actions = [transition.action for transition in transitions]
        self._unique(actions, "transition action")
        status_set = set(status_slugs)
        for transition in transitions:
            if transition.action in {"trash", "restore", "purge"}:
                raise ValueError(f"transition action is reserved: {transition.action}")
            if not transition.from_statuses:
                raise ValueError(f"transition {transition.action} needs a source status")
            if any(status not in status_set for status in transition.from_statuses):
                raise ValueError(f"transition {transition.action} references unknown status")
            if transition.to_status not in status_set:
                raise ValueError(f"transition {transition.action} references unknown status")
            if not transition.capability:
                raise ValueError(f"transition {transition.action} needs a capability")

        fields = self._fields(declaration)
        self._unique([field.slug for field in fields], "field")
        for field in fields:
            self._validate_field(field)

        taxonomy_groups = self._taxonomy_groups(declaration)
        self._unique([group.slug for group in taxonomy_groups], "taxonomy group")
        for group in taxonomy_groups:
            self._validate_slug(group.slug, "taxonomy group slug", 32)
            if not group.title:
                raise ValueError("taxonomy group title must not be empty")

        comment_policy = getattr(declaration, "comment_policy", CommentPolicy())
        trash_policy = getattr(declaration, "trash_policy", TrashPolicy())
        self._validate_policies(comment_policy, trash_policy)

        return ContentTypeDefinition(
            type_name=type_name,
            statuses=statuses,
            default_status=default_status,
            transitions=transitions,
            fields=fields,
            taxonomy_groups=taxonomy_groups,
            comment_policy=comment_policy,
            trash_policy=trash_policy,
        ).with_immutable_constraints()

    def validate_data(
        self, definition: ContentTypeDefinition, values: Mapping[str, Any]
    ) -> ContentDataValues:
        if not isinstance(values, Mapping):
            raise TypeError("content data must be a mapping")

        fields = {field.slug: field for field in definition.fields}
        unknown = set(values) - set(fields)
        if unknown:
            raise ValueError(f"unknown content data field: {sorted(unknown)[0]}")

        normalized: dict[str, str] = {}
        for slug, field in fields.items():
            if slug not in values:
                if field.required:
                    raise ValueError(f"required content data field missing: {slug}")
                continue
            raw = values[slug]
            if raw is None:
                if field.required:
                    raise ValueError(f"required content data field missing: {slug}")
                continue
            value = self._normalize_value(field, raw)
            if field.validator is not None:
                value = field.validator(value)
                if not isinstance(value, str):
                    raise ValueError(f"validator for {slug} must return str")
            self._validate_constraints(field, value)
            normalized[slug] = value

        return ContentDataValues.model_validate(normalized)

    @staticmethod
    def _required_class_string(declaration: type[ContentType], name: str) -> str:
        value = getattr(declaration, name, None)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} is required")
        return value

    @classmethod
    def _statuses(cls, declaration: type[ContentType]) -> tuple[ContentStatusDef, ...]:
        statuses = getattr(declaration, "statuses", None)
        if not isinstance(statuses, tuple) or not statuses:
            raise ValueError("statuses must be a non-empty tuple")
        if not all(isinstance(status, ContentStatusDef) for status in statuses):
            raise TypeError("statuses must contain ContentStatusDef values")
        for status in statuses:
            cls._validate_slug(status.slug, "status slug", 32)
        return statuses

    @classmethod
    def _transitions(cls, declaration: type[ContentType]) -> tuple[ContentTransitionDef, ...]:
        transitions = getattr(declaration, "transitions", ())
        if not isinstance(transitions, tuple):
            raise TypeError("transitions must be a tuple")
        if not all(isinstance(item, ContentTransitionDef) for item in transitions):
            raise TypeError("transitions must contain ContentTransitionDef values")
        for transition in transitions:
            if not _SLUG.fullmatch(transition.action):
                raise ValueError("transition action must be lowercase slug-like text")
        return transitions

    @classmethod
    def _fields(cls, declaration: type[ContentType]) -> tuple[ContentField, ...]:
        fields = getattr(declaration, "fields", None)
        if not isinstance(fields, tuple):
            raise ValueError("fields must be a tuple")
        if not all(isinstance(item, ContentField) for item in fields):
            raise TypeError("fields must contain ContentField values")
        return fields

    @classmethod
    def _taxonomy_groups(cls, declaration: type[ContentType]) -> tuple[TaxonomyGroupDef, ...]:
        groups = getattr(declaration, "taxonomy_groups", ())
        if not isinstance(groups, tuple):
            raise TypeError("taxonomy_groups must be a tuple")
        if not all(isinstance(item, TaxonomyGroupDef) for item in groups):
            raise TypeError("taxonomy_groups must contain TaxonomyGroupDef values")
        return groups

    @classmethod
    def _validate_field(cls, field: ContentField) -> None:
        cls._validate_slug(field.slug, "field slug", 64)
        if not field.title:
            raise ValueError("content field title must not be empty")
        if field.input_type not in _INPUT_TYPES:
            raise ValueError(f"unknown content field input_type: {field.input_type}")
        if not callable(field.validator) and field.validator is not None:
            raise TypeError(f"validator for {field.slug} must be callable")
        if not isinstance(field.constraints, Mapping):
            raise TypeError(f"constraints for {field.slug} must be a mapping")

    @staticmethod
    def _validate_policies(comment: CommentPolicy, trash: TrashPolicy) -> None:
        if not isinstance(comment, CommentPolicy):
            raise TypeError("comment_policy must be CommentPolicy")
        if comment.max_depth < 0 or comment.rate_limit < 0:
            raise ValueError("comment policy limits must not be negative")
        if not isinstance(trash, TrashPolicy):
            raise TypeError("trash_policy must be TrashPolicy")
        if trash.retention_days <= 0:
            raise ValueError("trash retention_days must be positive")

    @staticmethod
    def _validate_slug(value: str, label: str, max_length: int) -> None:
        pattern = re.compile(rf"^[a-z][a-z0-9_-]{{0,{max_length - 1}}}$")
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise ValueError(f"{label} must be lowercase slug-like text")

    @staticmethod
    def _unique(values: list[str], label: str) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {label} declaration")

    @classmethod
    def _normalize_value(cls, field: ContentField, raw: Any) -> str:
        input_type = field.input_type
        if input_type in {"bool", "boolean"}:
            if isinstance(raw, bool):
                return "true" if raw else "false"
            if isinstance(raw, str) and raw.strip().lower() in {
                "true",
                "false",
                "1",
                "0",
                "yes",
                "no",
                "on",
                "off",
            }:
                return "true" if raw.strip().lower() in {"true", "1", "yes", "on"} else "false"
            raise ValueError(f"invalid bool value for {field.slug}")

        if input_type in {"number", "num", "integer"}:
            if isinstance(raw, bool):
                raise ValueError(f"invalid number value for {field.slug}")
            try:
                decimal = Decimal(str(raw).strip())
            except InvalidOperation, ValueError:
                raise ValueError(f"invalid number value for {field.slug}") from None
            if input_type == "integer" and decimal != decimal.to_integral_value():
                raise ValueError(f"invalid integer value for {field.slug}")
            return str(raw).strip()

        value = cls._scalar_string(raw, field.slug)
        if input_type == "url":
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"invalid URL value for {field.slug}")
        return value

    @staticmethod
    def _scalar_string(raw: Any, slug: str) -> str:
        if isinstance(raw, (dict, list, tuple, set)):
            raise ValueError(f"invalid scalar value for {slug}")
        return str(raw)

    @staticmethod
    def _validate_constraints(field: ContentField, value: str) -> None:
        constraints = field.constraints
        if "min_length" in constraints and len(value) < int(constraints["min_length"]):
            raise ValueError(f"content field {field.slug} is shorter than min_length")
        if "max_length" in constraints and len(value) > int(constraints["max_length"]):
            raise ValueError(f"content field {field.slug} is longer than max_length")
        if "pattern" in constraints and re.fullmatch(str(constraints["pattern"]), value) is None:
            raise ValueError(f"content field {field.slug} does not match pattern")
