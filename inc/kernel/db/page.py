"""Pagination primitive.

Contract source: context/spec/kernel/database.md §4.

Page/size queries return ``items, total, page, size`` where ``total`` counts
with the same filter conditions. The caller owns the stable final ordering
key; this helper only applies offset/limit and derives the count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

MAX_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    size: int


async def fetch_page(
    session: AsyncSession,
    statement: Any,
    *,
    page: int,
    size: int,
) -> Page[Any]:
    """Execute *statement* with pagination and same-filter total."""

    if page < 1:
        raise ValueError("page must be >= 1")
    if not 1 <= size <= MAX_PAGE_SIZE:
        raise ValueError(f"size must be between 1 and {MAX_PAGE_SIZE}")

    count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
    total = (await session.execute(count_statement)).scalar_one()
    rows = (await session.execute(statement.offset((page - 1) * size).limit(size))).scalars().all()
    return Page(items=list(rows), total=total, page=page, size=size)
