"""Kernel taxonomy application service."""

from __future__ import annotations

from builtins import list as ListType
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from inc.kernel.content import ContentTypeDefinition, ContentTypeRegistry
from inc.kernel.db import Page, UoWExecutor, integrity_to_app_error
from inc.kernel.errors import AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.rbac import RBAC_001, check_capability
from inc.kernel.security import Principal

from .errors import TERM_001, TERM_002, TERM_003, TERM_004, TERM_005
from .events import TAXONOMY_EVENT_TYPES, TermAssignedPayload, TermEventPayload
from .models import Term, TermData
from .schemas import ContentTerms, TermAssign, TermCreate, TermListQuery, TermRead, TermUpdate
from .uow import TaxonomyUnitOfWork

ContentExists = Callable[[str, UUID], bool | Awaitable[bool]]


class TermService:
    """Validate taxonomy scope from declarative ContentType definitions."""

    def __init__(
        self,
        executor: UoWExecutor[TaxonomyUnitOfWork],
        *,
        content_registry: ContentTypeRegistry,
        event_bus: EventBus | None = None,
        content_exists: ContentExists | None = None,
    ) -> None:
        self._executor = executor
        self._registry = content_registry
        self._event_bus = event_bus or get_event_bus()
        self._content_exists = content_exists
        for event_type in TAXONOMY_EVENT_TYPES:
            if not self._event_bus.is_registered(event_type):
                self._event_bus.register(event_type)
        if not self._event_bus.is_registered("content.deleted"):
            self._event_bus.register("content.deleted")
        self._event_bus.subscribe("content.deleted", self._on_content_deleted)

    async def list(self, type_name: str, query: TermListQuery) -> Page[TermRead]:
        await self._validate_type(type_name)
        if query.group is not None:
            self._validate_group(type_name, query.group)

        async def operation(uow: TaxonomyUnitOfWork) -> Page[TermRead]:
            result = await uow.terms.list_filtered(
                type_name,
                group=query.group,
                slug=query.slug,
                q=query.q,
                created_from=query.created_from,
                created_to=query.created_to,
                updated_from=query.updated_from,
                updated_to=query.updated_to,
                page=query.page,
                size=query.size,
                sort=query.sort,
                order=query.order,
            )
            return Page(
                items=[self._to_read(term) for term in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )

        return await self._executor.read(operation)

    async def get(self, type_name: str, term_id: UUID) -> TermRead:
        await self._validate_type(type_name)

        async def operation(uow: TaxonomyUnitOfWork) -> TermRead:
            term = await uow.terms.get_or_none(term_id)
            if term is None or term.content_type != type_name:
                raise AppError(TERM_001)
            return self._to_read(term)

        return await self._executor.read(operation)

    async def create(self, type_name: str, dto: TermCreate, principal: Principal) -> TermRead:
        self._require_manage(principal)
        await self._validate_type(type_name)
        self._validate_group(type_name, dto.group)

        async def operation(uow: TaxonomyUnitOfWork) -> Term:
            term = Term(
                content_type=type_name,
                group=dto.group,
                slug=dto.slug,
                name=dto.name,
                data=TermData.model_validate(dto.data),
            )
            await uow.terms.add(term)
            return term

        try:
            term = await self._executor.write(operation)
        except IntegrityError as exc:
            raise AppError(TERM_003) from exc
        self._publish(
            "term.created",
            TermEventPayload(term_id=term.id, content_type=term.content_type, group=term.group),
            actor_id=principal.id,
        )
        return self._to_read(term)

    async def update(
        self, type_name: str, term_id: UUID, dto: TermUpdate, principal: Principal
    ) -> TermRead:
        self._require_manage(principal)
        await self._validate_type(type_name)

        async def operation(uow: TaxonomyUnitOfWork) -> Term:
            term = await uow.terms.get_for_update_or_none(term_id)
            if term is None or term.content_type != type_name:
                raise AppError(TERM_001)
            group = dto.group or term.group
            self._validate_group(type_name, group)
            if dto.group is not None:
                term.group = dto.group
            if dto.slug is not None:
                term.slug = dto.slug
            if dto.name is not None:
                term.name = dto.name
            if dto.data is not None:
                term.data = TermData.model_validate(dto.data)
            return term

        try:
            term = await self._executor.write(operation)
        except IntegrityError as exc:
            raise AppError(TERM_003) from exc
        self._publish(
            "term.updated",
            TermEventPayload(term_id=term.id, content_type=term.content_type, group=term.group),
            actor_id=principal.id,
        )
        return self._to_read(term)

    async def delete(self, type_name: str, term_id: UUID, principal: Principal) -> None:
        self._require_manage(principal)
        await self._validate_type(type_name)

        async def operation(uow: TaxonomyUnitOfWork) -> Term:
            term = await uow.terms.get_or_none(term_id)
            if term is None or term.content_type != type_name:
                raise AppError(TERM_001)
            await uow.terms.delete(term)
            return term

        try:
            term = await self._executor.write(operation)
        except IntegrityError as exc:
            raise integrity_to_app_error(exc) from exc
        self._publish(
            "term.deleted",
            TermEventPayload(term_id=term.id, content_type=term.content_type, group=term.group),
            actor_id=principal.id,
        )

    async def assign(
        self, type_name: str, content_id: UUID, dto: TermAssign, principal: Principal
    ) -> ListType[TermRead]:
        self._require_assign(principal)
        await self._validate_type(type_name)
        if self._content_exists is not None and not await _maybe(
            self._content_exists(type_name, content_id)
        ):
            raise AppError(TERM_004)

        async def operation(uow: TaxonomyUnitOfWork) -> ListType[Term]:
            terms = await self._load_terms(uow, dto.term_ids)
            if any(term.content_type != type_name for term in terms):
                raise AppError(TERM_004)
            await uow.relationships.replace(content_id, [term.id for term in terms])
            return terms

        terms = await self._executor.write(operation)
        self._publish(
            "term.assigned",
            TermAssignedPayload(
                content_id=content_id,
                term_ids=tuple(term.id for term in terms),
                actor_id=principal.id,
            ),
            actor_id=principal.id,
        )
        return [self._to_read(term) for term in terms]

    async def terms_for_contents(self, content_ids: Sequence[UUID]) -> dict[UUID, ContentTerms]:
        async def operation(uow: TaxonomyUnitOfWork) -> dict[UUID, ContentTerms]:
            mapping = await uow.terms.list_for_content(content_ids)
            return {
                content_id: ContentTerms(
                    terms=[self._to_read(term) for term in mapping.get(content_id, [])]
                )
                for content_id in content_ids
            }

        return await self._executor.read(operation)

    async def content_ids_for_filter(self, content_type: str, expression: str) -> ListType[UUID]:
        await self._validate_type(content_type)
        groups: dict[str, tuple[str, ...]] = {}
        for token in (part.strip() for part in expression.split(",")):
            if not token:
                continue
            group, separator, slug = token.partition(":")
            if not separator or not group or not slug:
                raise ValueError("term filters must use group:slug syntax")
            self._validate_group(content_type, group)
            groups[group] = (*groups.get(group, ()), slug)

        async def operation(uow: TaxonomyUnitOfWork) -> ListType[UUID]:
            return await uow.terms.content_ids_for_filter(content_type, groups)

        return await self._executor.read(operation)

    async def _on_content_deleted(self, event: Event) -> None:
        payload = event.payload
        content_id = getattr(payload, "content_id", None)
        if not isinstance(content_id, UUID):
            return
        await self._executor.write(lambda uow: uow.relationships.delete_for_content(content_id))

    async def _load_terms(
        self, uow: TaxonomyUnitOfWork, term_ids: Sequence[UUID]
    ) -> ListType[Term]:
        if not term_ids:
            return []
        rows: ListType[Term] = []
        for term_id in dict.fromkeys(term_ids):
            term = await uow.terms.get_or_none(term_id)
            if term is None:
                raise AppError(TERM_001)
            rows.append(term)
        return rows

    def _validate_group(self, content_type: str, group: str) -> None:
        definition = self._require_type(content_type)
        if not any(item.slug == group for item in definition.taxonomy_groups):
            raise AppError(TERM_002)

    async def _validate_type(self, type_name: str) -> None:
        self._require_type(type_name)

    def _require_type(self, type_name: str) -> ContentTypeDefinition:
        try:
            return self._registry.require(type_name)
        except KeyError as exc:
            raise AppError(TERM_005, detail={"type": type_name}) from exc

    @staticmethod
    def _to_read(term: Term) -> TermRead:
        return TermRead(
            id=term.id,
            content_type=term.content_type,
            group=term.group,
            slug=term.slug,
            name=term.name,
            data=term.data.model_dump(mode="json"),
            created_at=term.created_at,
            updated_at=term.updated_at,
        )

    @staticmethod
    def _require_manage(principal: Principal) -> None:
        if not check_capability(principal, "term:manage"):
            raise AppError(RBAC_001, detail={"alias": "term:manage"})

    @staticmethod
    def _require_assign(principal: Principal) -> None:
        if not check_capability(principal, "term:assign"):
            raise AppError(RBAC_001, detail={"alias": "term:assign"})

    def _publish(self, event_type: str, payload: Any, *, actor_id: UUID | None = None) -> None:
        self._event_bus.publish(Event(type=event_type, payload=payload, actor_id=actor_id))


async def _maybe(value: bool | Awaitable[bool]) -> bool:
    return await value if hasattr(value, "__await__") else value
