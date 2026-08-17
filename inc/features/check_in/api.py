"""Authenticated self-service gateway for the check-in feature.

The HTTP layer exposes this gateway but does not coordinate identity, assets,
settings, points, or workflow state itself.  All cross-capability sequencing
stays here and uses public Commands/Queries only.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from inc.capabilities.assets import AssetQueries
from inc.capabilities.assets.commands import (
    FINALIZE_WORKFLOW_KEY,
    CreateUploadIntent,
    FinalizeAsset,
)
from inc.capabilities.assets.commands import (
    CommandContext as AssetCommandContext,
)
from inc.capabilities.assets.schemas import CreateUploadIntentInput, CreateUploadIntentResult
from inc.capabilities.identity import IdentityQueries
from inc.capabilities.identity.commands import (
    CommandContext as IdentityCommandContext,
)
from inc.capabilities.identity.commands import (
    UpdateProfile,
)
from inc.capabilities.identity.schemas import UpdateProfileInput
from inc.capabilities.points import DEFAULT_PROGRAM_KEY, PointBehaviorRegistry, PointsQueries
from inc.capabilities.settings import SettingsQueries
from inc.kernel.db import UoWFactory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.events import OutboxWriter
from inc.kernel.security import PasswordHasher
from inc.kernel.time import Clock
from inc.kernel.workflow import WorkflowRunner

from .schemas import BalanceViewDTO, MeDTO

REWARD_BEHAVIOR = "daily_check_in.reward"


class MeService:
    """Read and mutate the authenticated self-service profile."""

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        clock: Clock,
        outbox: OutboxWriter,
        hasher: PasswordHasher,
        runner: WorkflowRunner,
        identity_queries: IdentityQueries,
        points_queries: PointsQueries,
        behaviors: PointBehaviorRegistry,
        settings_queries: SettingsQueries,
        asset_queries: AssetQueries | None,
        asset_providers: Mapping[str, Any],
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._outbox = outbox
        self._hasher = hasher
        self._runner = runner
        self._identity_queries = identity_queries
        self._points_queries = points_queries
        self._behaviors = behaviors
        self._settings_queries = settings_queries
        self._asset_queries = asset_queries
        self._asset_providers = dict(asset_providers)

    def _identity_context(self, *, subject_id: str, trace_id: str | None) -> IdentityCommandContext:
        return IdentityCommandContext(
            uow_factory=self._uow_factory,
            clock=self._clock,
            outbox=self._outbox,
            hasher=self._hasher,
            audit_actor_id=subject_id,
            audit_trace_id=trace_id,
        )

    def _asset_context(self, *, subject_id: str, trace_id: str | None) -> AssetCommandContext:
        if self._asset_queries is None or not self._asset_providers:
            raise KernelError(
                code="assets.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="assets capability is not available",
            )
        return AssetCommandContext(
            uow_factory=self._uow_factory,
            clock=self._clock,
            outbox=self._outbox,
            providers=dict(self._asset_providers),
            runner=self._runner,
            permissions=frozenset({"assets.upload", "assets.read"}),
            actor_id=subject_id,
            trace_id=trace_id,
        )

    async def get(self, *, subject_id: str, capabilities: frozenset[str]) -> MeDTO:
        subject = await self._identity_queries.get_subject(subject_id)
        if subject is None:
            raise KernelError(
                code="identity.not_found",
                category=ErrorCategory.NOT_FOUND,
                message="subject disappeared",
            )

        avatar_url: str | None = None
        if subject.avatar_asset_id is not None and self._asset_queries is not None:
            try:
                permissions = capabilities
                asset_id = uuid.UUID(subject.avatar_asset_id)
                if "assets.read" not in permissions:
                    asset = await self._asset_queries.get(
                        asset_id, permissions=frozenset({"assets.read"})
                    )
                    avatar_bucket = await self._settings_queries.get_value(
                        "object_storage", "s3_avatar_bucket"
                    )
                    if asset is None or asset.bucket != avatar_bucket:
                        raise KernelError(
                            code="assets.forbidden",
                            category=ErrorCategory.FORBIDDEN,
                            message="avatar is not in the subject avatar bucket",
                        )
                    permissions = frozenset({"assets.read"})
                avatar_url = (
                    await self._asset_queries.resolve_url(asset_id, permissions=permissions)
                ).url
            except (KernelError, ValueError) as _exc:
                del _exc
                # A deleted, pending or malformed asset is represented as no URL;
                # the stable opaque ID remains useful for profile management.
                avatar_url = None

        points: BalanceViewDTO | None = None
        try:
            program_key = self._behaviors.require(REWARD_BEHAVIOR).program_key
        except KernelError as exc:
            if exc.code != "points.unknown_behavior":
                raise
        else:
            try:
                balance = await self._points_queries.get_balance(
                    program_key=program_key,
                    subject_type="identity",
                    subject_id=subject.id,
                )
            except KernelError as exc:
                if exc.code not in {"points.account_not_opened", "points.program_inactive"}:
                    raise
                points = BalanceViewDTO(
                    opened=False,
                    program_key=program_key or DEFAULT_PROGRAM_KEY,
                    balance=0,
                )
            else:
                points = BalanceViewDTO(
                    opened=True,
                    program_key=balance.program_key,
                    balance=balance.balance,
                )

        return MeDTO(
            subject_id=subject.id,
            username=subject.username,
            display_name=subject.display_name,
            avatar_asset_id=subject.avatar_asset_id,
            avatar_url=avatar_url,
            status=subject.status,
            capabilities=sorted(capabilities),
            points=points,
        )

    async def update(
        self,
        *,
        subject_id: str,
        changes: UpdateProfileInput,
        capabilities: frozenset[str],
        trace_id: str | None,
    ) -> MeDTO:
        await UpdateProfile(self._identity_context(subject_id=subject_id, trace_id=trace_id))(
            user_id=subject_id,
            changes=changes,
        )
        return await self.get(subject_id=subject_id, capabilities=capabilities)

    async def create_avatar_upload_intent(
        self,
        *,
        subject_id: str,
        trace_id: str | None,
        mime_types: tuple[str, ...],
        content_length_max: int,
    ) -> CreateUploadIntentResult:
        asset_context = self._asset_context(subject_id=subject_id, trace_id=trace_id)
        avatar_bucket = await self._settings_queries.get_value("object_storage", "s3_avatar_bucket")
        return await CreateUploadIntent(asset_context)(
            CreateUploadIntentInput(
                provider_key="s3",
                bucket=avatar_bucket,
                mime_types=mime_types,
                content_length_max=content_length_max,
            )
        )

    async def finalize_avatar_upload(
        self,
        *,
        subject_id: str,
        trace_id: str | None,
        intent_id: uuid.UUID,
        capabilities: frozenset[str],
    ) -> MeDTO:
        asset_context = self._asset_context(subject_id=subject_id, trace_id=trace_id)
        await FinalizeAsset(asset_context)(intent_id)
        instance = await self._runner.find_by_business_key(
            workflow_key=FINALIZE_WORKFLOW_KEY,
            idempotency_key=f"intent:{intent_id}",
        )
        if instance is None:
            raise KernelError(
                code="assets.finalize_not_started",
                category=ErrorCategory.CONFLICT,
                message="avatar finalize workflow was not started",
            )
        await self._runner.advance(instance.id)
        asset_queries = self._asset_queries
        if asset_queries is None:
            raise KernelError(
                code="assets.unavailable",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                message="assets capability is not available",
            )
        asset = await asset_queries.get_by_upload_intent(
            intent_id,
            permissions=frozenset({"assets.read"}),
        )
        if asset is None:
            raise KernelError(
                code="assets.finalize_pending",
                category=ErrorCategory.CONFLICT,
                message="avatar upload has not reached ready state",
            )
        await UpdateProfile(self._identity_context(subject_id=subject_id, trace_id=trace_id))(
            user_id=subject_id,
            changes=UpdateProfileInput(avatar_asset_id=asset.id),
        )
        return await self.get(subject_id=subject_id, capabilities=capabilities)
