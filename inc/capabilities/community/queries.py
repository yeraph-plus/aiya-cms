"""Side-effect-free community queries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import aliased

from inc.capabilities.community.models import (
    CommunityDiscussion,
    CommunityDiscussionTag,
    CommunityPost,
    CommunitySearchDocument,
    CommunityTag,
)
from inc.capabilities.community.ports import CommunityAuthorPort
from inc.capabilities.community.schemas import (
    CommunityAuthorDTO,
    CommunityPageDTO,
    DiscussionDTO,
    DiscussionTagDTO,
    PostDTO,
    TagDTO,
)
from inc.capabilities.community.search import SEARCH_PROFILE, escape_like, normalize_query
from inc.capabilities.community.types import DiscussionTemplateRegistry, DiscussionTemplateSpec
from inc.kernel.db import UoWFactory, fetch_page
from inc.kernel.errors import ErrorCategory, KernelError


def _error(code: str, category: ErrorCategory, message: str) -> KernelError:
    return KernelError(code=code, category=category, message=message)


def _ensure_utc(value: Any) -> Any:
    from datetime import UTC

    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _required_utc(value: Any) -> Any:
    from datetime import UTC

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def _project(
    port: CommunityAuthorPort | None,
    references: Sequence[tuple[str, str]],
) -> dict[tuple[str, str], CommunityAuthorDTO]:
    if port is None or not references:
        return {}
    try:
        projector = getattr(port, "project", None) or getattr(port, "project_authors", None)
        if projector is None:
            raise RuntimeError("author port has no projection method")
        return cast(
            dict[tuple[str, str], CommunityAuthorDTO],
            await projector(tuple(dict.fromkeys(references))),
        )
    except KernelError:
        raise
    except Exception as exc:  # noqa: BLE001 - provider boundary
        raise _error(
            "community.author_provider_unavailable",
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            "community author provider is unavailable",
        ) from exc


def _tag_dto(row: CommunityTag, *, count: int = 0, position: int | None = None) -> TagDTO:
    return TagDTO(
        id=str(row.id),
        kind=row.kind,
        name=row.name,
        slug=row.slug,
        description=row.description,
        color=row.color,
        icon_key=row.icon_key,
        parent_id=str(row.parent_id) if row.parent_id else None,
        position=row.position if position is None else position,
        status=row.status,
        published_discussion_count=count,
        version=row.version,
    )


def _post_dto(
    row: CommunityPost,
    author: CommunityAuthorDTO | None,
    *,
    spec: DiscussionTemplateSpec | None = None,
) -> PostDTO:
    visible = row.status == "published"
    return PostDTO(
        id=str(row.id),
        discussion_id=str(row.discussion_id),
        number=row.number,
        post_type=row.post_type,
        status=row.status,
        author_type=row.author_type,
        author_id=row.author_id,
        author=author,
        body=row.body if visible and row.status != "deleted" else None,
        body_format="markdown",
        body_profile=row.body_profile,
        schema_version=row.schema_version,
        data=(
            spec.public_data(dict(row.data.payload))
            if spec is not None and visible and row.status != "deleted"
            else {}
        ),
        version=row.version,
        created_at=_required_utc(row.created_at),
        updated_at=_required_utc(row.updated_at),
        edited_at=_ensure_utc(row.edited_at),
        published_at=_ensure_utc(row.published_at),
        hidden_at=_ensure_utc(row.hidden_at),
        deleted_at=_ensure_utc(row.deleted_at),
    )


class CommunityQueries:
    """Read-only public and administrator community surface."""

    def __init__(
        self,
        *,
        uow_factory: UoWFactory,
        templates: DiscussionTemplateRegistry,
        author_port: CommunityAuthorPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._templates = templates
        self._author_port = author_port

    async def list_discussions(
        self,
        *,
        page: int,
        size: int,
        q: str | None = None,
        tag: str | None = None,
        sort: str | None = None,
    ) -> CommunityPageDTO[DiscussionDTO]:
        normalized_query: str | None = None
        tokens: tuple[str, ...] = ()
        if q is not None:
            normalized_query, tokens = normalize_query(q)
        if sort is None:
            sort = "relevance" if normalized_query is not None else "latest"
        if sort not in {"latest", "top", "newest", "relevance"}:
            raise _error(
                "community.invalid_sort",
                ErrorCategory.VALIDATION,
                f"invalid community sort {sort!r}",
            )
        if sort == "relevance" and normalized_query is None:
            raise _error("community.invalid_sort", ErrorCategory.VALIDATION, "relevance requires q")
        async with self._uow_factory() as uow:
            statement: Any = select(CommunityDiscussion)
            statement = statement.where(CommunityDiscussion.status == "published")
            if tag is not None:
                tag_exists = exists(
                    select(CommunityDiscussionTag.id)
                    .join(CommunityTag, CommunityTag.id == CommunityDiscussionTag.tag_id)
                    .where(
                        CommunityDiscussionTag.discussion_id == CommunityDiscussion.id,
                        CommunityTag.slug == tag,
                        CommunityTag.status == "active",
                    )
                )
                statement = statement.where(tag_exists)
            rank_expression: Any | None = None
            if normalized_query is not None:
                visible_document = self._visible_search_document()
                for token in tokens:
                    escaped = escape_like(token)
                    statement = statement.where(
                        exists(
                            select(CommunitySearchDocument.id).where(
                                CommunitySearchDocument.discussion_id == CommunityDiscussion.id,
                                visible_document,
                                CommunitySearchDocument.normalized_text.like(
                                    f"%{escaped}%", escape="\\"
                                ),
                            )
                        )
                    )
                escaped_query = escape_like(normalized_query)
                rank_expression = (
                    select(
                        func.max(
                            case(
                                (CommunitySearchDocument.normalized_text == normalized_query, 3.0),
                                (
                                    CommunitySearchDocument.normalized_text.like(
                                        f"{escaped_query}%", escape="\\"
                                    ),
                                    2.5,
                                ),
                                (
                                    CommunitySearchDocument.normalized_text.like(
                                        f"%{escaped_query}%", escape="\\"
                                    ),
                                    2.0,
                                ),
                                else_=1.0,
                            )
                        )
                    )
                    .where(
                        CommunitySearchDocument.discussion_id == CommunityDiscussion.id,
                        visible_document,
                    )
                    .correlate(CommunityDiscussion)
                    .scalar_subquery()
                )
            if sort == "latest":
                statement = statement.order_by(
                    CommunityDiscussion.last_posted_at.desc().nullslast(),
                    CommunityDiscussion.id.desc(),
                )
            elif sort == "top":
                statement = statement.order_by(
                    CommunityDiscussion.reply_count.desc(),
                    CommunityDiscussion.last_posted_at.desc().nullslast(),
                    CommunityDiscussion.id.desc(),
                )
            elif sort == "newest":
                statement = statement.order_by(
                    CommunityDiscussion.created_at.desc(), CommunityDiscussion.id.desc()
                )
            else:
                assert rank_expression is not None
                statement = statement.order_by(
                    rank_expression.desc(),
                    CommunityDiscussion.last_posted_at.desc().nullslast(),
                    CommunityDiscussion.id.desc(),
                )
            result = await fetch_page(uow.session, statement, page=page, size=size)
            rows = list(result.items)
            author_map = await _project(
                self._author_port, [(row.author_type, row.author_id) for row in rows]
            )
            items: list[DiscussionDTO] = []
            for row in rows:
                item = await self._discussion_dto(
                    uow, row, author_map.get((row.author_type, row.author_id))
                )
                items.append(item)
            return CommunityPageDTO(
                items=items, total=result.total, page=result.page, size=result.size
            )
        raise RuntimeError("community discussion query did not execute")

    async def get_discussion(self, discussion_id: uuid.UUID) -> DiscussionDTO | None:
        async with self._uow_factory() as uow:
            row = await uow.session.get(CommunityDiscussion, discussion_id)
            if row is None:
                return None
            author_map = await _project(self._author_port, [(row.author_type, row.author_id)])
            return await self._discussion_dto(
                uow, row, author_map.get((row.author_type, row.author_id))
            )
        raise RuntimeError("community discussion query did not execute")

    async def get_published_by_slug(self, slug: str) -> DiscussionDTO | None:
        async with self._uow_factory() as uow:
            row = (
                (
                    await uow.session.execute(
                        select(CommunityDiscussion).where(
                            CommunityDiscussion.slug == slug,
                            CommunityDiscussion.status == "published",
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if row is None:
                return None
            author_map = await _project(self._author_port, [(row.author_type, row.author_id)])
            return await self._discussion_dto(
                uow, row, author_map.get((row.author_type, row.author_id))
            )
        raise RuntimeError("community slug query did not execute")

    async def list_posts(
        self,
        discussion_id: uuid.UUID,
        *,
        page: int,
        size: int,
    ) -> CommunityPageDTO[PostDTO]:
        async with self._uow_factory() as uow:
            statement = (
                select(CommunityPost)
                .join(CommunityDiscussion, CommunityDiscussion.id == CommunityPost.discussion_id)
                .where(
                    CommunityPost.discussion_id == discussion_id,
                    CommunityDiscussion.status == "published",
                    CommunityPost.status == "published",
                )
                .order_by(CommunityPost.number.asc(), CommunityPost.id.asc())
            )
            result = await fetch_page(uow.session, statement, page=page, size=size)
            rows = list(result.items)
            discussion = await uow.session.get(CommunityDiscussion, discussion_id)
            spec = self._templates.require(discussion.template_key) if discussion else None
            author_map = await _project(
                self._author_port, [(row.author_type, row.author_id) for row in rows]
            )
            return CommunityPageDTO(
                items=[
                    _post_dto(
                        row,
                        author_map.get((row.author_type, row.author_id)),
                        spec=spec,
                    )
                    for row in rows
                ],
                total=result.total,
                page=result.page,
                size=result.size,
            )
        raise RuntimeError("community post query did not execute")

    async def list_admin_discussions(
        self,
        *,
        page: int,
        size: int,
        status: str | None = None,
        author_id: str | None = None,
    ) -> CommunityPageDTO[DiscussionDTO]:
        async with self._uow_factory() as uow:
            statement = select(CommunityDiscussion)
            if status is not None:
                statement = statement.where(CommunityDiscussion.status == status)
            if author_id is not None:
                statement = statement.where(CommunityDiscussion.author_id == author_id)
            statement = statement.order_by(
                CommunityDiscussion.updated_at.desc(), CommunityDiscussion.id.desc()
            )
            result = await fetch_page(uow.session, statement, page=page, size=size)
            rows = list(result.items)
            author_map = await _project(
                self._author_port, [(row.author_type, row.author_id) for row in rows]
            )
            return CommunityPageDTO(
                items=[
                    await self._discussion_dto(
                        uow, row, author_map.get((row.author_type, row.author_id))
                    )
                    for row in rows
                ],
                total=result.total,
                page=result.page,
                size=result.size,
            )
        raise RuntimeError("community admin discussion query did not execute")

    async def list_admin_posts(
        self,
        *,
        page: int,
        size: int,
        discussion_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> CommunityPageDTO[PostDTO]:
        async with self._uow_factory() as uow:
            statement = select(CommunityPost)
            if discussion_id is not None:
                statement = statement.where(CommunityPost.discussion_id == discussion_id)
            if status is not None:
                statement = statement.where(CommunityPost.status == status)
            statement = statement.order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc())
            result = await fetch_page(uow.session, statement, page=page, size=size)
            rows = list(result.items)
            author_map = await _project(
                self._author_port, [(row.author_type, row.author_id) for row in rows]
            )
            specs: dict[uuid.UUID, DiscussionTemplateSpec] = {}
            for row in rows:
                discussion = await uow.session.get(CommunityDiscussion, row.discussion_id)
                if discussion is not None:
                    specs[row.discussion_id] = self._templates.require(discussion.template_key)
            return CommunityPageDTO(
                items=[
                    _post_dto(
                        row,
                        author_map.get((row.author_type, row.author_id)),
                        spec=specs.get(row.discussion_id),
                    )
                    for row in rows
                ],
                total=result.total,
                page=result.page,
                size=result.size,
            )
        raise RuntimeError("community admin post query did not execute")

    async def list_tags(
        self,
        *,
        kind: str | None = None,
        parent_id: uuid.UUID | None = None,
        include_archived: bool = False,
    ) -> list[TagDTO]:
        parent = aliased(CommunityTag)
        published_count = (
            select(func.count(func.distinct(CommunityDiscussionTag.discussion_id)))
            .join(
                CommunityDiscussion,
                CommunityDiscussion.id == CommunityDiscussionTag.discussion_id,
            )
            .where(
                CommunityDiscussionTag.tag_id == CommunityTag.id,
                CommunityDiscussion.status == "published",
            )
            .correlate(CommunityTag)
            .scalar_subquery()
        )
        async with self._uow_factory() as uow:
            statement = select(CommunityTag, published_count.label("published_count")).outerjoin(
                parent, parent.id == CommunityTag.parent_id
            )
            if kind is not None:
                statement = statement.where(CommunityTag.kind == kind)
            if parent_id is not None:
                statement = statement.where(CommunityTag.parent_id == parent_id)
            if not include_archived:
                statement = statement.where(CommunityTag.status == "active")
            statement = statement.order_by(
                case((CommunityTag.kind == "primary", 0), else_=1),
                func.coalesce(parent.position, -1),
                CommunityTag.position,
                CommunityTag.name,
                CommunityTag.id,
            )
            rows = (await uow.session.execute(statement)).all()
            return [_tag_dto(tag, count=int(count or 0)) for tag, count in rows]
        raise RuntimeError("community tag query did not execute")

    async def get_tag_by_slug(self, slug: str, *, include_archived: bool = False) -> TagDTO | None:
        async with self._uow_factory() as uow:
            statement = select(CommunityTag).where(CommunityTag.slug == slug)
            if not include_archived:
                statement = statement.where(CommunityTag.status == "active")
            row = (await uow.session.execute(statement)).scalars().one_or_none()
            if row is None:
                return None
            count = int(
                (
                    await uow.session.execute(
                        select(func.count(func.distinct(CommunityDiscussionTag.discussion_id)))
                        .join(
                            CommunityDiscussion,
                            CommunityDiscussion.id == CommunityDiscussionTag.discussion_id,
                        )
                        .where(
                            CommunityDiscussionTag.tag_id == row.id,
                            CommunityDiscussion.status == "published",
                        )
                    )
                ).scalar_one()
            )
            return _tag_dto(row, count=count)
        raise RuntimeError("community tag query did not execute")

    async def _discussion_dto(
        self,
        uow: Any,
        row: CommunityDiscussion,
        author: CommunityAuthorDTO | None,
    ) -> DiscussionDTO:
        tags = (
            await uow.session.execute(
                select(CommunityTag, CommunityDiscussionTag.position)
                .join(CommunityDiscussionTag, CommunityDiscussionTag.tag_id == CommunityTag.id)
                .where(CommunityDiscussionTag.discussion_id == row.id)
                .order_by(CommunityDiscussionTag.position, CommunityTag.name, CommunityTag.id)
            )
        ).all()
        return DiscussionDTO(
            id=str(row.id),
            template_key=row.template_key,
            schema_version=row.schema_version,
            title=row.title,
            slug=row.slug,
            status=row.status,
            author_type=row.author_type,
            author_id=row.author_id,
            author=author,
            data=self._templates.require(row.template_key).public_data(dict(row.data.payload)),
            is_locked=row.is_locked,
            locked_at=_ensure_utc(row.locked_at),
            locked_by_type=row.locked_by_type,
            locked_by_id=row.locked_by_id,
            first_post_id=str(row.first_post_id) if row.first_post_id else None,
            last_post_id=str(row.last_post_id) if row.last_post_id else None,
            reply_count=row.reply_count,
            last_posted_at=_ensure_utc(row.last_posted_at),
            version=row.version,
            created_at=_required_utc(row.created_at),
            updated_at=_required_utc(row.updated_at),
            published_at=_ensure_utc(row.published_at),
            hidden_at=_ensure_utc(row.hidden_at),
            archived_at=_ensure_utc(row.archived_at),
            tags=[
                DiscussionTagDTO(
                    id=str(tag.id),
                    kind=tag.kind,
                    name=tag.name,
                    slug=tag.slug,
                    description=tag.description,
                    color=tag.color,
                    icon_key=tag.icon_key,
                    parent_id=str(tag.parent_id) if tag.parent_id else None,
                    position=position,
                    status=tag.status,
                    version=tag.version,
                )
                for tag, position in tags
            ],
        )

    @staticmethod
    def _visible_search_document() -> Any:
        return and_(
            CommunitySearchDocument.search_profile == SEARCH_PROFILE,
            or_(
                and_(
                    CommunitySearchDocument.document_kind == "title",
                    CommunitySearchDocument.source_version == CommunityDiscussion.version,
                ),
                and_(
                    CommunitySearchDocument.document_kind == "post",
                    exists(
                        select(CommunityPost.id).where(
                            CommunityPost.id == CommunitySearchDocument.post_id,
                            CommunityPost.status == "published",
                            CommunityPost.discussion_id == CommunitySearchDocument.discussion_id,
                            CommunityPost.version == CommunitySearchDocument.source_version,
                        )
                    ),
                ),
            ),
        )
