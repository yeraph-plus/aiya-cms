"""Taxonomy queries.

Contract source: context/spec/capabilities/taxonomy.md §5.

FindTargetsByTerms returns opaque target ids: terms of the same dimension
are OR-ed, terms of different dimensions are AND-ed. No joins into target
capability tables; stable ordering by position/name/id.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from inc.capabilities.taxonomy.dimensions import DimensionRegistry
from inc.capabilities.taxonomy.models import TaxonomyAssignment, TaxonomyTerm
from inc.capabilities.taxonomy.schemas import DimensionDTO, TermDTO
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError


class TaxonomyQueries:
    """Read-only taxonomy surface."""

    def __init__(self, *, uow_factory: UoWFactory, dimensions: DimensionRegistry) -> None:
        self._uow_factory = uow_factory
        self._dimensions = dimensions

    async def list_dimensions(self) -> list[DimensionDTO]:
        out: list[DimensionDTO] = []
        for spec in self._dimensions.specs():
            out.append(
                DimensionDTO(
                    dimension_key=spec.dimension_key,
                    version=spec.version,
                    display_name=spec.display_name,
                    selection_mode=spec.selection_mode,
                    min_items=spec.min_items,
                    max_items=spec.max_items,
                    public_visible=spec.public_visible,
                )
            )
        return out

    async def list_terms(  # type: ignore[return]
        self,
        dimension_key: str,
        *,
        include_archived: bool = False,
    ) -> list[TermDTO]:
        self._dimensions.require(dimension_key)
        async with self._uow_factory() as uow:
            statement = select(TaxonomyTerm).where(TaxonomyTerm.dimension_key == dimension_key)
            if not include_archived:
                statement = statement.where(TaxonomyTerm.status == "active")
            statement = statement.order_by(TaxonomyTerm.name, TaxonomyTerm.id)
            rows = (await uow.session.execute(statement)).scalars().all()
            return [self._to_dto(row) for row in rows]

    async def get_target_terms(self, target_type: str, target_id: Any) -> dict[str, list[TermDTO]]:
        async with self._uow_factory() as uow:
            rows = (
                await uow.session.execute(
                    select(TaxonomyAssignment, TaxonomyTerm)
                    .join(TaxonomyTerm, TaxonomyTerm.id == TaxonomyAssignment.term_id)
                    .where(
                        TaxonomyAssignment.target_type == target_type,
                        TaxonomyAssignment.target_id == target_id,
                    )
                    .order_by(
                        TaxonomyAssignment.dimension_key,
                        TaxonomyAssignment.position,
                        TaxonomyTerm.name,
                    )
                )
            ).all()
        grouped: dict[str, list[TermDTO]] = {}
        for assignment, term in rows:
            grouped.setdefault(assignment.dimension_key, []).append(self._to_dto(term))
        return grouped

    async def find_targets_by_terms(self, dimensions: dict[str, list[str]]) -> list[str]:
        """Opaque target keys (``type:id``) matching OR-within / AND-across."""

        candidates: set[str] | None = None
        for dimension_key, term_ids in dimensions.items():
            try:
                self._dimensions.require(dimension_key)
            except KernelError as exc:
                if exc.code == "taxonomy.unknown_dimension":
                    raise KernelError(
                        code="taxonomy.unknown_dimension",
                        category=ErrorCategory.VALIDATION,
                        message=exc.message,
                    ) from exc
                raise
            if not term_ids:
                continue
            try:
                term_uuids = [uuid.UUID(term_id) for term_id in term_ids]
            except ValueError as exc:
                raise KernelError(
                    code="taxonomy.invalid_uuid",
                    category=ErrorCategory.VALIDATION,
                    message="one or more term ids are not valid uuids",
                ) from exc
            async with self._uow_factory() as uow:
                rows = (
                    await uow.session.execute(
                        select(TaxonomyAssignment.target_type, TaxonomyAssignment.target_id)
                        .join(TaxonomyTerm, TaxonomyTerm.id == TaxonomyAssignment.term_id)
                        .where(
                            TaxonomyAssignment.dimension_key == dimension_key,
                            TaxonomyAssignment.term_id.in_(term_uuids),
                            TaxonomyTerm.status == "active",
                        )
                    )
                ).all()
            requested = {f"{row[0]}:{row[1]}" for row in rows}
            if candidates is None:
                candidates = requested
            else:
                candidates &= requested
            if not candidates:
                return []
        return sorted(candidates) if candidates is not None else []

    @staticmethod
    def _to_dto(row: TaxonomyTerm) -> TermDTO:
        return TermDTO(
            id=str(row.id),
            dimension_key=row.dimension_key,
            name=row.name,
            slug=row.slug,
            description=row.description,
            metadata=dict(row.term_metadata.values),
            status=row.status,
        )
