"""Taxonomy events.

Contract source: context/spec/capabilities/taxonomy.md §7.

Assignment events carry target refs and term id sets, never target
business data.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from inc.kernel.errors import validate_error_code


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_key: str


class TermCreatedPayload(_Base):
    term_id: str
    slug: str
    name: str


class TermUpdatedPayload(_Base):
    term_id: str
    slug: str


class TermArchivedPayload(_Base):
    term_id: str
    slug: str


class AssignmentsReplacedPayload(_Base):
    target_type: str
    target_id: str
    term_ids: tuple[str, ...] = ()


TAXONOMY_EVENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "taxonomy.term_created.v1": TermCreatedPayload,
    "taxonomy.term_updated.v1": TermUpdatedPayload,
    "taxonomy.term_archived.v1": TermArchivedPayload,
    "taxonomy.assignments_replaced.v1": AssignmentsReplacedPayload,
}

for _key in TAXONOMY_EVENT_SCHEMAS:
    validate_error_code(_key)
