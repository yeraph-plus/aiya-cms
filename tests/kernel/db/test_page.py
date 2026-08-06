"""Red tests locking the Page DTO (M1.2 db).

Contract source: context/kernel/db-uow-repository.md §3/§6
"""

import pytest
from pydantic import ValidationError

from inc.kernel.db import Page


def test_page_carries_items_total_page_size() -> None:
    page = Page[int](items=[1, 2, 3], total=100, page=1, size=10)

    assert page.items == [1, 2, 3]
    assert page.total == 100
    assert page.page == 1
    assert page.size == 10


def test_page_rejects_zero_page() -> None:
    with pytest.raises(ValidationError):
        Page[int](items=[], total=0, page=0, size=10)


def test_page_rejects_zero_size() -> None:
    with pytest.raises(ValidationError):
        Page[int](items=[], total=0, page=1, size=0)
