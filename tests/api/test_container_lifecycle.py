"""Release container lifecycle and provider catalog tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from inc.api.config import ApiSettings
from inc.api.container import ApplicationContainer, build_container
from inc.api.manifest import release
from inc.kernel.boot import AppManifest
from inc.kernel.errors import KernelError


@pytest.fixture
def settings(tmp_path: Any) -> ApiSettings:
    return ApiSettings(issuer="http://testserver", oidc_signing_key_dir=str(tmp_path / "keys"))


async def test_start_stop_is_idempotent_and_clean(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    container = build_container(
        manifest=release, uow_factory=uow_factory, clock=clock, settings=settings
    )
    await container.start()
    assert len(container._tasks) == 4
    with pytest.raises(KernelError, match="already started"):
        await container.start()
    await container.stop()
    assert container._tasks == []


async def test_provider_catalog_registers_all_allowed_providers(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    container = build_container(
        manifest=release, uow_factory=uow_factory, clock=clock, settings=settings
    )
    assert container.provider_catalogs["notification.email"].keys() == (
        "email.smtp",
        "email.smtp2go",
    )
    assert container.provider_catalogs["payments.provider"].keys() == ("epay", "paypal")
    assert container.provider_catalogs["assets.object_storage"].keys() == ("s3",)
    assert await container.selected_provider_key("payments.provider") == "paypal"


async def test_release_builds_with_production_settings(
    uow_factory: Any, clock: Any, tmp_path: Any
) -> None:
    settings = ApiSettings(
        environment="production",
        issuer="https://cms.example.com",
        secure_cookies=True,
        cors_origins=("https://cms.example.com",),
        oidc_signing_key_dir=str(tmp_path / "keys"),
        admin_session_secret="test-admin-session-secret-0123456789012345",
    )
    container = build_container(
        manifest=release, uow_factory=uow_factory, clock=clock, settings=settings
    )
    assert container.frozen
    assert container.manifest.name == "release"


async def test_legacy_production_manifest_is_rejected(
    uow_factory: Any, clock: Any, tmp_path: Any
) -> None:
    settings = ApiSettings(
        environment="production",
        issuer="https://cms.example.com",
        secure_cookies=True,
        cors_origins=("https://cms.example.com",),
        oidc_signing_key_dir=str(tmp_path / "keys"),
        admin_session_secret="test-admin-session-secret-0123456789012345",
    )
    with pytest.raises(KernelError) as exc_info:
        build_container(
            manifest=AppManifest(name="legacy", capabilities=()),
            uow_factory=uow_factory,
            clock=clock,
            settings=settings,
        )
    assert exc_info.value.code == "kernel.production_manifest_denied"


async def test_start_requires_frozen_container(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    container = ApplicationContainer(
        manifest=release, uow_factory=uow_factory, clock=clock, settings=settings
    )
    container.build()
    with pytest.raises(KernelError) as exc_info:
        await container.start()
    assert exc_info.value.code == "kernel.container_not_frozen"


async def test_start_cancels_workers_cleanly_after_assertion(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    container = build_container(
        manifest=release, uow_factory=uow_factory, clock=clock, settings=settings
    )
    await container.start()
    await asyncio.sleep(0)
    await container.stop()
