"""Explicit, freeze-on-start ContentType registry."""

from __future__ import annotations

from collections.abc import Iterable

from .definitions import ContentType, ContentTypeDefinition
from .interpreter import ContentTypeInterpreter


class ContentTypeRegistry:
    """Compile and store concrete declarations without auto-discovery."""

    def __init__(
        self,
        declarations: Iterable[type[ContentType]] = (),
        *,
        interpreter: ContentTypeInterpreter | None = None,
    ) -> None:
        self._interpreter = interpreter or ContentTypeInterpreter()
        self._definitions: dict[str, ContentTypeDefinition] = {}
        self._frozen = False
        for declaration in declarations:
            self.register(declaration)

    def register(self, declaration: type[ContentType]) -> None:
        if self._frozen:
            raise RuntimeError("content type registry is frozen")
        definition = self._interpreter.compile(declaration)
        if definition.type_name in self._definitions:
            raise ValueError(f"duplicate content type: {definition.type_name}")
        self._definitions[definition.type_name] = definition

    def require(self, type_name: str) -> ContentTypeDefinition:
        try:
            return self._definitions[type_name]
        except KeyError:
            raise KeyError(f"unknown content type: {type_name}") from None

    def keys(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def freeze(self) -> None:
        self._frozen = True

    def clear(self) -> None:
        if self._frozen:
            raise RuntimeError("content type registry is frozen")
        self._definitions.clear()
