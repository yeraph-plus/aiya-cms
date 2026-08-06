"""Taxonomy diagnostics: read-only orphan probe.

Contract source: context/spec/capabilities/taxonomy.md §6.

Reports assignment targets that no longer exist through the consumer
Port; never deletes or repairs.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from inc.capabilities.taxonomy.models import TaxonomyAssignment
from inc.capabilities.taxonomy.ports import BatchTargetExistsPort
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus


class TaxonomyDiagnostics:
    key = "taxonomy"

    def __init__(
        self, *, uow_factory: UoWFactory, batch_target_exists: BatchTargetExistsPort
    ) -> None:
        self._uow_factory = uow_factory
        self._batch_target_exists = batch_target_exists

    async def run(self) -> list[DiagnosticResult]:
        async with self._uow_factory() as uow:
            rows = (
                await uow.session.execute(
                    select(
                        TaxonomyAssignment.target_type,
                        TaxonomyAssignment.target_id,
                        TaxonomyAssignment.dimension_key,
                    ).distinct()
                )
            ).all()
        by_type: dict[str, list[str]] = defaultdict(list)
        for target_type, target_id, _dimension in rows:
            by_type[target_type].append(str(target_id))
        orphan_count = 0
        for target_type, target_ids in by_type.items():
            exists = await self._batch_target_exists(target_type, target_ids)
            orphan_count += sum(1 for target_id in target_ids if not exists.get(target_id, False))
        return [
            DiagnosticResult(
                code="taxonomy.orphan_assignments",
                status=DiagnosticStatus.OK if orphan_count == 0 else DiagnosticStatus.DEGRADED,
                summary=f"{orphan_count} assignment targets no longer exist",
            )
        ]
