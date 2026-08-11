"""Container lifecycle and fail-fast tests.

Contract source: context/spec/composition.md §5/§6/§9, kernel/boot.md §3/§5.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from inc.api.config import ApiSettings
from inc.api.container import build_container
from inc.api.manifest import cms, kernel_only
from inc.kernel.boot import AppManifest
from inc.kernel.errors import KernelError


@pytest.fixture
def settings() -> ApiSettings:
    return ApiSettings(issuer="http://testserver")


async def test_start_stop_is_idempotent_and_clean(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    container = build_container(
        manifest=cms, uow_factory=uow_factory, clock=clock, settings=settings
    )
    await container.start()
    assert len(container._tasks) == 4  # outbox + workflow + CronScheduler + TaskWorker
    with pytest.raises(KernelError) as excinfo:
        await container.start()  # double start must fail
    assert excinfo.value.code == "kernel.container_already_started"
    await container.stop()
    assert container._tasks == []
    await container.stop()  # stop is idempotent


async def test_cms_registers_cron_work_with_kernel_task_runtime(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    container = build_container(
        manifest=cms, uow_factory=uow_factory, clock=clock, settings=settings
    )

    assert "content.publish.scan.v1" in container.cron_registry.keys()
    assert "points.buckets.expire.v1" in container.cron_registry.keys()
    assert "membership.subscription.expire.v1" in container.cron_registry.keys()
    assert "oidc.keys.cleanup.v1" in container.cron_registry.keys()
    assert "site.cleanup.retention.v1" in container.cron_registry.keys()
    assert "content.publish.scan.v1.tick" in container.task_registry.keys()
    assert "site.cleanup.retention.v1.tick" in container.task_registry.keys()


async def test_start_requires_frozen_container(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    from inc.api.container import ApplicationContainer

    container = ApplicationContainer(
        manifest=cms, uow_factory=uow_factory, clock=clock, settings=settings
    )
    container.build()  # not frozen
    with pytest.raises(KernelError) as excinfo:
        await container.start()
    assert excinfo.value.code == "kernel.container_not_frozen"


async def test_unknown_router_in_manifest_fails(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    manifest = AppManifest(name="bad", capabilities=("audit",), routers=("cotennt",))
    with pytest.raises(KernelError) as excinfo:
        build_container(manifest=manifest, uow_factory=uow_factory, clock=clock, settings=settings)
    assert excinfo.value.code == "kernel.registry_unknown"


async def test_unknown_worker_in_manifest_fails(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    manifest = AppManifest(name="bad", capabilities=("audit",), workers=("outboxx",))
    with pytest.raises(KernelError) as excinfo:
        build_container(manifest=manifest, uow_factory=uow_factory, clock=clock, settings=settings)
    assert excinfo.value.code == "kernel.registry_unknown"


async def test_duplicate_manifest_entries_fail(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    manifest = AppManifest(name="bad", capabilities=("audit", "audit"))
    with pytest.raises(KernelError) as excinfo:
        build_container(manifest=manifest, uow_factory=uow_factory, clock=clock, settings=settings)
    assert excinfo.value.code == "kernel.manifest_duplicate"


async def test_production_denies_dev_payment_adapter(uow_factory: Any, clock: Any) -> None:
    production = ApiSettings(
        environment="production",
        issuer="https://cms.example.com",
        secure_cookies=True,
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(manifest=cms, uow_factory=uow_factory, clock=clock, settings=production)
    assert excinfo.value.code == "kernel.adapter_production_denied"


async def test_production_requires_https_and_secure_cookies() -> None:
    from inc.api.config import load_api_settings

    with pytest.raises(ValueError, match="https"):
        load_api_settings({"environment": "production", "issuer": "http://insecure.example"})
    with pytest.raises(ValueError, match="secure cookies"):
        load_api_settings({"environment": "production", "issuer": "https://cms.example.com"})
    with pytest.raises(ValueError, match="https"):
        # hostless https:// must be rejected too
        load_api_settings({"environment": "production", "issuer": "https://"})
    with pytest.raises(ValueError):
        # unknown environment value is rejected by the Literal constraint
        ApiSettings(environment="Production")


async def test_production_gate_holds_on_direct_construction() -> None:
    """The production invariant must hold regardless of construction path —
    not only through load_api_settings."""
    with pytest.raises(ValueError, match="https"):
        ApiSettings(environment="production", issuer="http://insecure.example")
    with pytest.raises(ValueError, match="secure cookies"):
        ApiSettings(environment="production", issuer="https://cms.example.com")


async def test_assets_s3_provider_only_created_when_bound(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    """Assets resolves the explicit S3 provider and fails closed when unbound."""
    manifest_with_s3 = AppManifest(
        name="with-s3-storage",
        capabilities=("assets",),
        routers=("assets",),
        adapters=(("assets.object_storage", "assets.s3"),),
    )
    container_s3 = build_container(
        manifest=manifest_with_s3, uow_factory=uow_factory, clock=clock, settings=settings
    )
    assert container_s3.services.asset_providers["s3"].key == "s3"

    manifest_unknown = AppManifest(
        name="unknown-storage",
        capabilities=("assets",),
        routers=("assets",),
        adapters=(("assets.object_storage", "assets.unknown"),),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest_unknown, uow_factory=uow_factory, clock=clock, settings=settings
        )
    assert excinfo.value.code == "kernel.adapter_unknown"

    # assets with no object_storage binding fails closed on the required port
    manifest_unbound = AppManifest(
        name="no-dev-storage",
        capabilities=("assets",),
        routers=("assets",),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(
            manifest=manifest_unbound, uow_factory=uow_factory, clock=clock, settings=settings
        )
    assert excinfo.value.code == "kernel.port_unbound"


async def test_oidc_without_identity_fails_on_capability_dependency(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    manifest = AppManifest(
        name="bad",
        capabilities=("oidc_provider", "access", "audit"),
        adapters=(
            ("oidc.subject_authenticator", "identity.credential"),
            ("oidc.subject_claims", "identity.profile"),
            ("oidc.authorization_decision", "access.authorize"),
            ("oidc.security_events", "oidc.session_revoker"),
        ),
    )
    with pytest.raises(KernelError) as excinfo:
        build_container(manifest=manifest, uow_factory=uow_factory, clock=clock, settings=settings)
    assert excinfo.value.code == "kernel.capability_requires_missing"


async def test_worker_loop_survives_failures_and_logs(
    uow_factory: Any, clock: Any, settings: ApiSettings
) -> None:
    container = build_container(
        manifest=kernel_only, uow_factory=uow_factory, clock=clock, settings=settings
    )

    async def failing() -> None:
        raise RuntimeError("boom")

    task = asyncio.create_task(container._loop("test", failing, sleep_seconds=0.01))
    container._tasks.append(task)
    await asyncio.sleep(0.05)
    assert not task.done()  # loop survived the failure
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_secure_cookie_env_parsing_accepts_truthy_spellings() -> None:
    """AIYA_SECURE_COOKIES must accept common truthy values, so a deployment
    writing "true"/"yes"/" on " does not silently disable the Secure flag on
    the OIDC login session cookie."""
    from inc.main import _parse_bool

    for truthy in ("1", "true", "TRUE", "True", "yes", "on", " on "):
        assert _parse_bool(truthy) is True, truthy
    for falsy in ("0", "false", "", "anything", None):
        assert _parse_bool(falsy) is False, falsy
    assert _parse_bool(None, default=True) is True
