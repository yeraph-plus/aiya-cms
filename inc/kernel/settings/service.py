"""Runtime settings service with declarative interpretation and sparse overrides."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel

from inc.kernel.cache import Cache, cache_key
from inc.kernel.db import UoWExecutor
from inc.kernel.errors import AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.security import Principal

from .definitions import SettingField
from .errors import SETTING_001, SETTING_002
from .events import SETTING_EVENT_TYPES, SettingUpdatedPayload
from .interpreter import SettingInterpreter
from .models import Setting, SettingGroupRead, SettingOverrides, SettingPatch
from .registry import SettingDefinition, SettingRegistry, setting_registry
from .uow import SettingsUnitOfWork


class SettingsService:
    def __init__(
        self,
        executor: UoWExecutor[SettingsUnitOfWork],
        cache: Cache,
        *,
        registry: SettingRegistry | None = None,
        event_bus: EventBus | None = None,
        clock: Callable[[], datetime] | None = None,
        cache_ttl: int = 300,
    ) -> None:
        self._executor = executor
        self._cache = cache
        self._registry = registry or setting_registry
        self._event_bus = event_bus or get_event_bus()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cache_ttl = cache_ttl
        for event_type in SETTING_EVENT_TYPES:
            if not self._event_bus.is_registered(event_type):
                self._event_bus.register(event_type)

    async def get(self, key: str) -> BaseModel:
        definition = self._definition(key)
        interpreter = SettingInterpreter(definition)
        cache_value = await self._cache.get(self._cache_key(key))
        if cache_value is not None:
            try:
                return interpreter.model.model_validate(json.loads(cache_value))
            except TypeError, ValueError:
                await self._cache.delete(self._cache_key(key))

        async def operation(uow: SettingsUnitOfWork) -> Setting | None:
            return await uow.settings.get_by_key(key)

        row = await self._executor.read(operation)
        overrides = {} if row is None else row.value.root
        try:
            value = interpreter.resolve(overrides)
        except ValueError as exc:
            raise AppError(SETTING_002, detail={"key": key}, cause=exc) from exc
        await self._cache.set(
            self._cache_key(key), json.dumps(value.model_dump(mode="json")), self._cache_ttl
        )
        return value

    async def get_field[T](self, field: SettingField[T]) -> T:
        """Resolve one declared field for internal callers with a typed handle."""

        value = await self.get(self._field_group(field).slug)
        return cast(T, getattr(value, field.slug))

    async def list(self) -> list[SettingGroupRead]:
        result: list[SettingGroupRead] = []
        for definition in sorted(self._registry.definitions(), key=lambda item: item.group.order):
            interpreter = SettingInterpreter(definition)

            async def operation(
                uow: SettingsUnitOfWork, key: str = definition.key
            ) -> Setting | None:
                return await uow.settings.get_by_key(key)

            row = await self._executor.read(operation)
            overrides = {} if row is None else row.value.root
            try:
                resolved = interpreter.resolve(overrides)
                result.append(interpreter.describe(resolved, overrides))
            except ValueError as exc:
                raise AppError(SETTING_002, detail={"key": definition.key}, cause=exc) from exc
        return result

    async def public(self, key: str) -> dict[str, Any]:
        definition = self._definition(key)
        interpreter = SettingInterpreter(definition)
        value = await self.get(key)
        return interpreter.public_values(value)

    async def update(self, key: str, patch: SettingPatch, actor: Principal) -> SettingGroupRead:
        definition = self._definition(key)
        interpreter = SettingInterpreter(definition)

        async def operation(
            uow: SettingsUnitOfWork,
        ) -> tuple[BaseModel, SettingOverrides, tuple[str, ...]]:
            row = await uow.settings.get_for_update_by_key(key)
            current = {} if row is None else row.value.root
            try:
                resolved, overrides = interpreter.apply_patch(current, patch)
            except ValueError as exc:
                raise AppError(SETTING_002, detail={"key": key}, cause=exc) from exc
            if overrides.root:
                if row is None:
                    row = Setting(
                        key=key,
                        value=overrides,
                        updated_by=None if actor.is_anonymous else actor.id,
                        updated_at=self._now(),
                    )
                    await uow.settings.add(row)
                else:
                    row.value = overrides
                    row.updated_by = None if actor.is_anonymous else actor.id
                    row.updated_at = self._now()
            elif row is not None:
                await uow.settings.delete(row)
            changed = tuple(sorted(set(patch.values) | set(patch.unset)))
            return resolved, overrides, changed

        resolved, overrides, changed = await self._executor.write(operation)
        await self._cache.set(
            self._cache_key(key), json.dumps(resolved.model_dump(mode="json")), self._cache_ttl
        )
        self._event_bus.publish(
            Event(
                type="setting.updated",
                payload=SettingUpdatedPayload(
                    key=key, changed_fields=list(changed), actor_id=actor.id
                ),
            )
        )
        return interpreter.describe(resolved, overrides.root)

    def _definition(self, key: str) -> SettingDefinition:
        definition = self._registry.get(key)
        if definition is None:
            raise AppError(SETTING_001, detail={"key": key})
        return definition

    def _field_group(self, field: SettingField[Any]) -> type[Any]:
        for definition in self._registry.definitions():
            if field in definition.fields:
                return definition.group
        raise AppError(SETTING_001, detail={"field": field.slug})

    @staticmethod
    def _cache_key(key: str) -> str:
        return cache_key("setting", key)

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)
