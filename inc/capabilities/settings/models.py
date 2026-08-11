"""Settings persistence models.

Contract source: context/spec/capabilities/settings.md §3.

``settings_values`` stores one row per registered group field.  Group
updates still use a shared group version so the physical row split does not
weaken group-level atomicity or optimistic concurrency.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin


class SettingValuePayload(BaseModel):
    """Pydantic-bound payload for one field's database value."""

    model_config = ConfigDict(extra="forbid")

    value: Any


@TableOwnership.owned_by("capability:settings")
class SettingsValue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settings_values"
    __table_args__ = (
        UniqueConstraint("group_key", "field_slug", name="uq_settings_values_group_field"),
        Index("ix_settings_values_group_key", "group_key"),
    )

    group_key: Mapped[str] = mapped_column(String(100), nullable=False)
    field_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[SettingValuePayload] = mapped_column(
        JsonBModel(SettingValuePayload, "1"), nullable=False
    )
    group_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
