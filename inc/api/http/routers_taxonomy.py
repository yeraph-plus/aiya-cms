"""Taxonomy admin router.

Contract source: context/spec/http-openapi.md, capabilities/taxonomy.md.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field

from inc.api.container import Services
from inc.api.http.context import AppContext, RequireCapability
from inc.capabilities.taxonomy.commands import (
    ArchiveTerm,
    AssignTerms,
    CommandContext,
    CreateTerm,
    RemoveTargetAssignments,
    UpdateTerm,
)
from inc.capabilities.taxonomy.schemas import (
    AssignTermsInput,
    CreateTermInput,
    DimensionDTO,
    TermDTO,
    UpdateTermInput,
)


class AssignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_key: str
    term_ids: list[uuid.UUID] = Field(default_factory=list)


class RemoveTargetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str
    target_id: str


def _ctx(ctx: AppContext, services: Services) -> CommandContext:
    return CommandContext(
        uow_factory=ctx.uow_factory,
        clock=ctx.clock,
        outbox=services.outbox,
        dimensions=services.dimensions,
        target_exists=_target_exists(ctx, services),
        permissions=frozenset(ctx.principal.capabilities),
        actor_id=ctx.principal.subject_id,
        trace_id=ctx.trace_id,
    )


def _target_exists(ctx: AppContext, services: Any) -> Any:
    async def _exists(target_type: str, target_id: str) -> bool:
        if target_type == "content":
            return await services.content_queries.get(target_id) is not None
        return False

    return _exists


REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "taxonomy.read",
    "taxonomy.manage",
)


def build_router(
    services: Services,
    require_capability: RequireCapability,
    require_authenticated: Any = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin")

    @router.get("/taxonomy/dimensions", response_model=list[DimensionDTO])
    async def list_dimensions(
        ctx: AppContext = Depends(require_capability("taxonomy.read")),
    ) -> list[DimensionDTO]:
        return await services.taxonomy_queries.list_dimensions()

    @router.get("/taxonomy/dimensions/{dimension_key}/terms", response_model=list[TermDTO])
    async def list_terms(
        dimension_key: str = Path(...),
        ctx: AppContext = Depends(require_capability("taxonomy.read")),
    ) -> list[TermDTO]:
        return await services.taxonomy_queries.list_terms(dimension_key)

    @router.post("/taxonomy/dimensions/{dimension_key}/terms", response_model=TermDTO)
    async def create_term(
        body: CreateTermInput,
        dimension_key: str = Path(...),
        ctx: AppContext = Depends(require_capability("taxonomy.manage")),
    ) -> TermDTO:
        return await CreateTerm(_ctx(ctx, services))(dimension_key, body)

    @router.patch("/taxonomy/terms/{term_id}", response_model=TermDTO)
    async def update_term(
        body: UpdateTermInput,
        term_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("taxonomy.manage")),
    ) -> TermDTO:
        return await UpdateTerm(_ctx(ctx, services))(term_id, body)

    @router.post("/taxonomy/terms/{term_id}/archive", response_model=TermDTO)
    async def archive_term(
        term_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("taxonomy.manage")),
    ) -> TermDTO:
        return await ArchiveTerm(_ctx(ctx, services))(term_id)

    @router.put("/taxonomy/targets/{target_type}/{target_id}/terms", status_code=204)
    async def assign_terms(
        body: AssignBody,
        target_type: str = Path(...),
        target_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("taxonomy.manage")),
    ) -> None:
        await AssignTerms(_ctx(ctx, services))(
            body.dimension_key,
            AssignTermsInput(
                target_type=target_type,
                target_id=target_id,
                term_ids=body.term_ids,
            ),
        )

    @router.delete("/taxonomy/targets/{target_type}/{target_id}/terms", status_code=204)
    async def remove_target_terms(
        target_type: str = Path(...),
        target_id: uuid.UUID = Path(...),
        ctx: AppContext = Depends(require_capability("taxonomy.manage")),
    ) -> None:
        await RemoveTargetAssignments(_ctx(ctx, services))(target_type, str(target_id))

    return router
