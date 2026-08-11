"""Side-effect-free comments queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from inc.capabilities.comments.commands import to_dto
from inc.capabilities.comments.models import Comment
from inc.capabilities.comments.schemas import CommentDTO
from inc.kernel.db import Page, UoWFactory, fetch_page


class CommentQueries:
    def __init__(self, *, uow_factory: UoWFactory) -> None:
        self._uow_factory = uow_factory

    async def list_published(
        self, target_type: str, target_id: str, *, page: int, size: int
    ) -> Page[CommentDTO]:
        statement = (
            select(Comment)
            .where(
                Comment.target_type == target_type,
                Comment.target_id == target_id,
                Comment.status == "published",
            )
            .order_by(Comment.submitted_at, Comment.id)
        )
        return await self._page(statement, page=page, size=size)

    async def list_admin(
        self,
        *,
        page: int,
        size: int,
        status: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        author_id: str | None = None,
    ) -> Page[CommentDTO]:
        statement = select(Comment)
        if status is not None:
            statement = statement.where(Comment.status == status)
        if target_type is not None:
            statement = statement.where(Comment.target_type == target_type)
        if target_id is not None:
            statement = statement.where(Comment.target_id == target_id)
        if author_id is not None:
            statement = statement.where(Comment.author_id == author_id)
        statement = statement.order_by(Comment.submitted_at.desc(), Comment.id.desc())
        return await self._page(statement, page=page, size=size)

    async def get(self, comment_id: uuid.UUID) -> CommentDTO | None:  # type: ignore[return]
        async with self._uow_factory() as uow:
            row = await uow.session.get(Comment, comment_id)
            return to_dto(row) if row is not None else None

    async def _page(  # type: ignore[return]
        self, statement: object, *, page: int, size: int
    ) -> Page[CommentDTO]:
        async with self._uow_factory() as uow:
            result = await fetch_page(uow.session, statement, page=page, size=size)
            return Page(
                items=[to_dto(row) for row in result.items],
                total=result.total,
                page=result.page,
                size=result.size,
            )
