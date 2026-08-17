"""Provider catalog and runtime settings selection contracts."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from inc.adapters.registry import ProviderCatalog, ProviderResolver
from inc.kernel.errors import ErrorCategory, KernelError


@dataclass(frozen=True)
class _Provider:
    key: str


class _Settings:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    async def get_value(self, group: str, field: str) -> str | None:
        assert (group, field) == ("notification", "email_provider")
        return self.value


def test_catalog_is_deterministic_and_freezes_at_boot() -> None:
    catalog: ProviderCatalog[_Provider] = ProviderCatalog("notification.email")
    catalog.register("email.smtp2go", _Provider("email.smtp2go"))
    catalog.register("email.smtp", _Provider("email.smtp"))

    assert catalog.keys() == ("email.smtp", "email.smtp2go")
    assert tuple(item.key for item in catalog.registrations()) == catalog.keys()

    with pytest.raises(KernelError) as duplicate:
        catalog.register("email.smtp", _Provider("email.smtp"))
    assert duplicate.value.code == "kernel.provider_duplicate"

    catalog.freeze()
    with pytest.raises(KernelError) as excinfo:
        catalog.register("email.other", _Provider("email.other"))
    assert excinfo.value.code == "kernel.registry_frozen"


@pytest.mark.asyncio
async def test_resolver_uses_settings_value_and_rejects_unknown_provider() -> None:
    catalog: ProviderCatalog[_Provider] = ProviderCatalog("notification.email")
    catalog.register("email.smtp", _Provider("email.smtp"))
    catalog.register("email.smtp2go", _Provider("email.smtp2go"))
    catalog.freeze()
    settings = _Settings("email.smtp2go")
    resolver = ProviderResolver(
        catalog=catalog,
        settings_queries=settings,
        settings_group="notification",
        settings_field="email_provider",
        default_key="email.smtp",
    )

    assert await resolver.selected_key() == "email.smtp2go"
    assert (await resolver.resolve()).key == "email.smtp2go"

    settings.value = "email.unknown"
    with pytest.raises(KernelError) as excinfo:
        await resolver.resolve()
    assert excinfo.value.code == "kernel.provider_unknown"
    assert excinfo.value.category is ErrorCategory.VALIDATION


@pytest.mark.asyncio
async def test_resolver_falls_back_to_composition_default_when_setting_is_empty() -> None:
    catalog: ProviderCatalog[_Provider] = ProviderCatalog("notification.email")
    catalog.register("email.smtp", _Provider("email.smtp"))
    catalog.register("email.smtp2go", _Provider("email.smtp2go"))
    catalog.freeze()
    resolver = ProviderResolver(
        catalog=catalog,
        settings_queries=_Settings(""),
        settings_group="notification",
        settings_field="email_provider",
        default_key="email.smtp2go",
    )

    assert await resolver.selected_key() == "email.smtp2go"
