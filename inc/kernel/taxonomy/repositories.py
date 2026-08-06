"""Kernel taxonomy repositories."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, or_, select

from inc.kernel.db import Page, Repository

from .models import Term, TermRelationship


class TermRepository(Repository[Term]):
    model = Term

    async def get_by_key(self, content_type: str, group: str, slug: str) -> Term | None:
        return cast(
            Term | None,
            await self.session.scalar(
                select(Term).where(
                    Term.content_type == content_type,
                    Term.group == group,
                    Term.slug == slug,
                )
            ),
        )

    async def list_filtered(
        self,
        content_type: str,
        *,
        group: str | None = None,
        slug: str | None = None,
        q: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        page: int = 1,
        size: int = 20,
        sort: str = "name",
        order: str = "asc",
    ) -> Page[Term]:
        filters = [Term.content_type == content_type]
        if group is not None:
            filters.append(Term.group == group)
        if slug is not None:
            filters.append(Term.slug == slug)
        if q:
            pattern = _contains_pattern(q)
            filters.append(
                or_(
                    Term.name.ilike(pattern, escape="\\"),
                    Term.slug.ilike(pattern, escape="\\"),
                )
            )
        if created_from is not None:
            filters.append(Term.created_at >= created_from)
        if created_to is not None:
            filters.append(Term.created_at <= created_to)
        if updated_from is not None:
            filters.append(Term.updated_at >= updated_from)
        if updated_to is not None:
            filters.append(Term.updated_at <= updated_to)
        try:
            order_column = {
                "group": Term.group,
                "name": Term.name,
                "slug": Term.slug,
                "created_at": Term.created_at,
                "updated_at": Term.updated_at,
            }[sort]
        except KeyError as exc:
            raise ValueError(f"unsupported term sort: {sort}") from exc
        ordering = order_column.asc() if order == "asc" else order_column.desc()
        ordering = ordering.nulls_last()
        tie_breaker = Term.id.asc() if order == "asc" else Term.id.desc()
        total = int(
            await self.session.scalar(select(func.count()).select_from(Term).where(*filters)) or 0
        )
        result = await self.session.scalars(
            select(Term)
            .where(*filters)
            .order_by(ordering, tie_breaker)
            .limit(size)
            .offset((page - 1) * size)
        )
        return Page(items=list(result.all()), total=total, page=page, size=size)

    async def list_for_content(self, content_ids: Sequence[UUID]) -> dict[UUID, list[Term]]:
        if not content_ids:
            return {}
        rows = await self.session.execute(
            select(TermRelationship.content_id, Term)
            .join(Term, Term.id == TermRelationship.term_id)
            .where(TermRelationship.content_id.in_(content_ids))
            .order_by(TermRelationship.content_id, Term.name, Term.id)
        )
        result: dict[UUID, list[Term]] = {}
        for content_id, term in rows.all():
            result.setdefault(content_id, []).append(term)
        return result

    async def content_ids_for_filter(
        self, content_type: str, groups: dict[str, tuple[str, ...]]
    ) -> list[UUID]:
        if not groups:
            return []
        clauses = [
            (Term.group == group) & Term.slug.in_(slugs) for group, slugs in groups.items() if slugs
        ]
        if not clauses:
            return []
        rows = await self.session.scalars(
            select(TermRelationship.content_id)
            .join(Term, Term.id == TermRelationship.term_id)
            .where(Term.content_type == content_type, or_(*clauses))
            .group_by(TermRelationship.content_id)
            .having(func.count(func.distinct(Term.group)) == len(clauses))
        )
        return list(rows.all())


class TermRelationshipRepository(Repository[TermRelationship]):
    model = TermRelationship

    async def replace(self, content_id: UUID, term_ids: Sequence[UUID]) -> None:
        await self.session.execute(
            delete(TermRelationship).where(TermRelationship.content_id == content_id)
        )
        if term_ids:
            self.session.add_all(
                [TermRelationship(content_id=content_id, term_id=term_id) for term_id in term_ids]
            )

    async def delete_for_content(self, content_id: UUID) -> None:
        await self.session.execute(
            delete(TermRelationship).where(TermRelationship.content_id == content_id)
        )


def _contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
