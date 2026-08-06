"""Settings persistence models.

Contract source: context/spec/capabilities/settings.md §3.

Only one table in the first version: settings_values, validated against
the registered group schema on every write. No secrets are stored here;
infrastructure secrets stay in kernel config/secret providers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from inc.kernel.db import Base, JsonBModel, TableOwnership, TimestampMixin, UUIDPrimaryKeyMixin


class SettingsValueData(BaseModel):
    """Schema-bound group value envelope."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    values: dict[str, object] = {}


@TableOwnership.owned_by("capability:settings")
class SettingsValue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settings_values"

    group_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[SettingsValueData] = mapped_column(
        JsonBModel(SettingsValueData, "1"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
