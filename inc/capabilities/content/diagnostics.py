"""Content diagnostics: read-only consistency probes.

Contract source: context/spec/capabilities/content.md §11.

Reports unknown types/schema versions, invalid state combinations, overdue
scheduled backlog, published rows without published_at, orphan references
and data schema mismatches. Never repairs.
"""

from __future__ import annotations

from sqlalchemy import func, select

from inc.capabilities.content.models import Content, ContentReference
from inc.capabilities.content.types import ContentTypeRegistry
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus
from inc.kernel.time import Clock


class ContentDiagnostics:
    key = "content"

    def __init__(
        self, *, uow_factory: UoWFactory, types: ContentTypeRegistry, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._types = types
        self._clock = clock

    async def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        async with self._uow_factory() as uow:
            rows = (
                await uow.session.execute(
                    select(
                        Content.type_name,
                        Content.schema_version,
                        func.count(Content.id),
                    ).group_by(Content.type_name, Content.schema_version)
                )
            ).all()
            unknown = []
            for type_name, schema_version, _count in rows:
                try:
                    spec = self._types.require(type_name)
                except Exception:
                    unknown.append(f"{type_name}/{schema_version} (unregistered type)")
                    continue
                if schema_version != spec.data_schema_version:
                    unknown.append(f"{type_name}/{schema_version} (schema mismatch)")
            results.append(
                DiagnosticResult(
                    code="content.unknown_type_or_schema",
                    status=DiagnosticStatus.OK if not unknown else DiagnosticStatus.DEGRADED,
                    summary=(
                        f"{len(unknown)} rows with unregistered type/schema: "
                        + ", ".join(unknown[:5])
                    ),
                )
            )

            published_missing_time = (
                await uow.session.execute(
                    select(func.count(Content.id)).where(
                        Content.status == "published", Content.published_at.is_(None)
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="content.published_missing_time",
                    status=(
                        DiagnosticStatus.OK
                        if published_missing_time == 0
                        else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{published_missing_time} published rows without published_at",
                )
            )

            overdue = (
                await uow.session.execute(
                    select(func.count(Content.id)).where(
                        Content.status == "scheduled",
                        Content.publish_at < self._clock.utc_now(),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="content.scheduled_overdue_backlog",
                    status=DiagnosticStatus.OK if overdue == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{overdue} scheduled rows past publish_at",
                )
            )

            orphan_refs = (
                await uow.session.execute(
                    select(func.count(ContentReference.id)).where(
                        ContentReference.target_content_id.notin_(select(Content.id))
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="content.orphan_references",
                    status=DiagnosticStatus.OK if orphan_refs == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{orphan_refs} references to missing content",
                )
            )
        return results
