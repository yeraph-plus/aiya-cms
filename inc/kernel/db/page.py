"""Generic pagination DTO (spec §3/§6)."""

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    """A slice of results plus the total count for a page/size window."""

    items: list[T]
    total: int
    page: int = Field(ge=1)
    size: int = Field(ge=1)
