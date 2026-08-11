"""Assets diagnostics: read-only consistency probes.

Contract source: context/spec/capabilities/assets.md §8.

Reports long-pending intents, failed/local-deleted backlog and, in a
bounded explicit run, ready-but-remote-missing objects via provider stat.
Never repairs.
"""

from __future__ import annotations

from sqlalchemy import func, select

from inc.capabilities.assets.models import AssetObject, AssetUploadIntent
from inc.capabilities.assets.ports import ObjectStorageProvider
from inc.kernel.db import UoWFactory
from inc.kernel.observability import DiagnosticResult, DiagnosticStatus
from inc.kernel.time import Clock

REMOTE_PROBE_LIMIT = 25


class AssetDiagnostics:
    key = "assets"

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        clock: Clock,
        providers: dict[str, ObjectStorageProvider],
        probe_remote: bool = False,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._providers = providers
        self._probe_remote = probe_remote

    async def run(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        async with self._uow_factory() as uow:
            pending = (
                await uow.session.execute(
                    select(func.count(AssetUploadIntent.id)).where(
                        AssetUploadIntent.consumed_at.is_(None),
                        AssetUploadIntent.expires_at < self._clock.utc_now(),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="assets.expired_pending_intents",
                    status=DiagnosticStatus.OK if pending == 0 else DiagnosticStatus.DEGRADED,
                    summary=f"{pending} expired unconsumed upload intents",
                )
            )

            failed_or_deleted = (
                await uow.session.execute(
                    select(func.count(AssetObject.id)).where(
                        AssetObject.state.in_(("failed", "deleted")),
                        AssetObject.external_deleted_at.is_(None),
                    )
                )
            ).scalar_one()
            results.append(
                DiagnosticResult(
                    code="assets.unresolved_objects",
                    status=(
                        DiagnosticStatus.OK if failed_or_deleted == 0 else DiagnosticStatus.DEGRADED
                    ),
                    summary=f"{failed_or_deleted} failed/deleted objects not confirmed external",
                )
            )

            if not self._probe_remote:
                return results
            ready = (
                (
                    await uow.session.execute(
                        select(AssetObject)
                        .where(AssetObject.state == "ready")
                        .order_by(AssetObject.updated_at.desc())
                        .limit(REMOTE_PROBE_LIMIT)
                    )
                )
                .scalars()
                .all()
            )
        # Remote probes run outside the database session so a slow provider
        # never holds a transaction open.
        missing = 0
        for row in ready:
            provider = self._providers.get(row.provider_key)
            if provider is None:
                missing += 1
                continue
            try:
                await provider.stat(bucket=row.bucket, object_key=row.object_key)
            except Exception:  # noqa: BLE001 - remote probe is best effort
                missing += 1
        results.append(
            DiagnosticResult(
                code="assets.ready_but_remote_missing",
                status=DiagnosticStatus.OK if missing == 0 else DiagnosticStatus.DEGRADED,
                summary=(
                    f"{missing}/{len(ready)} recently ready assets unreachable on remote "
                    f"(probed {REMOTE_PROBE_LIMIT} latest)"
                ),
            )
        )
        return results
