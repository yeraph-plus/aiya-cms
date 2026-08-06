"""Explicit mail-template registry."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class MailTemplate:
    name: str
    subject_template: str
    body_template: str
    context_model: type[BaseModel]


class MailTemplateRegistry:
    def __init__(self, templates: Iterable[MailTemplate] = ()) -> None:
        self._templates: dict[str, MailTemplate] = {}
        for template in templates:
            self.register(template)

    def register(self, template: MailTemplate) -> None:
        if not template.name or len(template.name) > 64:
            raise ValueError("mail template name must be 1-64 characters")
        if template.name in self._templates:
            raise ValueError(f"duplicate mail template: {template.name}")
        if not issubclass(template.context_model, BaseModel):
            raise TypeError("mail template context_model must be a Pydantic model")
        self._templates[template.name] = template

    def get(self, name: str) -> MailTemplate | None:
        return self._templates.get(name)

    def names(self) -> frozenset[str]:
        return frozenset(self._templates)

    def clear(self) -> None:
        self._templates.clear()


mail_template_registry = MailTemplateRegistry()


def register_mail_template(
    name: str,
    subject: str,
    body: str,
    ctx_model: type[BaseModel],
) -> None:
    mail_template_registry.register(MailTemplate(name, subject, body, ctx_model))


def clear_mail_template_registry() -> None:
    mail_template_registry.clear()
