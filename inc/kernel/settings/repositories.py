"""Settings persistence repository."""

from typing import cast

from sqlalchemy import select

from inc.kernel.db import Repository

from .models import Setting


class SettingsRepository(Repository[Setting]):
    model = Setting

    async def get_by_key(self, key: str) -> Setting | None:
        return cast(
            Setting | None, await self.session.scalar(select(Setting).where(Setting.key == key))
        )

    async def get_for_update_by_key(self, key: str) -> Setting | None:
        return cast(
            Setting | None,
            await self.session.scalar(select(Setting).where(Setting.key == key).with_for_update()),
        )
