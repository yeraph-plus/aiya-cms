"""Settings transaction boundary."""

from inc.kernel.db import AbstractUnitOfWork

from .repositories import SettingsRepository


class SettingsUnitOfWork(AbstractUnitOfWork):
    @property
    def settings(self) -> SettingsRepository:
        return SettingsRepository(self.session)
