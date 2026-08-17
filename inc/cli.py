"""Operations CLI.

Contract source: context/spec/access.md §4/§9 (single super admin bootstrap),
quality-release.md.

``python -m inc.cli migrate`` applies database migrations only (the single
Compose entry for running ``alembic upgrade head``). ``python -m inc.cli
install`` is the deployable release installation and the only path that
creates the super administrator. It applies migrations, creates the initial
filesystem-backed OIDC signing key, seeds the credit points program, registers
the admin and Astro client OIDC clients, and bootstraps the single administrator
user. The password is generated
when not provided and printed exactly once. Re-running is safe for the same
administrator but refuses to create a second one (``access.administrator_exists``).

All database/redis/server configuration is read from environment variables
(AIYA_DATABASE_URL, AIYA_REDIS_URL, AIYA_PUBLIC_BASE_URL, AIYA_SITE_BASE_URL,
AIYA_SITE_OIDC_CLIENT_SECRET, AIYA_API_AUDIENCE, etc.). There is no separate
bootstrap subcommand, no CLI password recovery,
and no CLI user create/delete commands.

The same entry also hosts the Compose-internalized quality gates:
``migrate``, ``quality`` (ruff/mypy/pip check), ``test`` (pytest),
``openapi-check`` and ``migration-check``. They run inside the backend image
so no extra Compose services are required.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from inc.api.manifest import release
from inc.capabilities.access import (
    BootstrapAdministrator,
    EnsureBaseRoles,
)
from inc.capabilities.access import (
    CommandContext as AccessCommandContext,
)
from inc.capabilities.identity import CommandContext as IdentityCommandContext
from inc.capabilities.identity.commands import RegisterLocalUser
from inc.kernel.config import load_settings
from inc.kernel.db import SqlAlchemyUnitOfWork, create_engine, create_session_factory
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.time import SYSTEM_CLOCK


def _build_factory() -> Any:
    kernel_settings = load_settings()
    engine = create_engine(kernel_settings.database_url.get_secret_value())
    session_factory = create_session_factory(engine)

    def factory() -> Any:
        return SqlAlchemyUnitOfWork(session_factory)

    return factory, engine


def _subject_exists(identity_queries: Any) -> Any:
    class _Exists:
        async def exists(self, subject_type: str, subject_id: str) -> bool:
            if subject_type == "identity":
                return await identity_queries.get_subject(subject_id) is not None
            return False

    return _Exists()


async def _create_admin(
    *, username: str, email: str, password: str | None, manifest: Any
) -> tuple[str, str | None]:
    from inc.api.container import build_container
    from inc.main import _api_settings_from_env

    factory, engine = _build_factory()
    try:
        container = build_container(
            manifest=manifest,
            uow_factory=factory,
            clock=SYSTEM_CLOCK,
            settings=_api_settings_from_env(),
        )
        services = container.services
        assert services is not None

        generated = not password
        effective_password = password or secrets.token_urlsafe(18)

        identity_ctx = IdentityCommandContext(
            uow_factory=factory,
            clock=SYSTEM_CLOCK,
            hasher=services.hasher,
            outbox=services.outbox,
            audit_actor_id="cli",
            audit_trace_id="install",
        )
        try:
            result = await RegisterLocalUser(identity_ctx)(
                username=username, email=email, password=effective_password
            )
            subject_id = result.subject.id
        except KernelError as exc:
            if exc.code != "identity.duplicate_identifier":
                raise
            existing = await services.identity_queries.find_by_login_identifier(username)
            if existing is None:
                existing = await services.identity_queries.find_by_login_identifier(email)
            if existing is None:
                raise KernelError(
                    code="cli.admin_subject_missing",
                    category=ErrorCategory.CONFLICT,
                    message=f"cannot resolve existing user for {username!r}/{email!r}",
                ) from exc
            subject_id = existing.id
            # The existing credential was not changed; do not report a fresh
            # random token that was never stored.
            generated = False

        access_ctx = AccessCommandContext(
            uow_factory=factory,
            clock=SYSTEM_CLOCK,
            outbox=services.outbox,
            permissions=services.permission_registry,
            subject_exists=_subject_exists(services.identity_queries),
            audit_actor_id="cli",
            audit_trace_id="install",
        )
        await EnsureBaseRoles(access_ctx)()
        await BootstrapAdministrator(access_ctx)(subject_type="identity", subject_id=subject_id)
        return subject_id, effective_password if generated else None
    finally:
        await engine.dispose()


def _run_migrations() -> None:
    """Run alembic upgrade head against the configured database_url."""
    from alembic.command import upgrade
    from alembic.config import Config as AlembicConfig

    kernel_settings = load_settings()
    database_url = kernel_settings.database_url.get_secret_value()
    root = Path(__file__).resolve().parent.parent
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    upgrade(cfg, "head")


async def _seed_points_program(factory: Any) -> None:
    from sqlalchemy import select

    from inc.capabilities.points.constants import DEFAULT_PROGRAM_KEY
    from inc.capabilities.points.models import PointsProgram

    async with factory() as uow:
        existing = (
            (
                await uow.session.execute(
                    select(PointsProgram).where(PointsProgram.program_key == DEFAULT_PROGRAM_KEY)
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            print("  points program credit already exists, skipping")
            return
        legacy = (
            (
                await uow.session.execute(
                    select(PointsProgram).where(PointsProgram.program_key == "default")
                )
            )
            .scalars()
            .first()
        )
        if legacy is not None:
            legacy.program_key = DEFAULT_PROGRAM_KEY
            legacy.display_name = "Credit"
            await uow.commit()
            print("  legacy default points program renamed to credit")
            return
        uow.session.add(
            PointsProgram(
                program_key=DEFAULT_PROGRAM_KEY,
                display_name="Credit",
                unit="points",
                status="active",
                allow_admin_reversal=True,
            )
        )
        await uow.commit()
    print("  credit points program seeded")


async def _seed_membership_levels(factory: Any) -> None:
    """Seed the production-safe basic membership level idempotently."""
    from sqlalchemy import select

    from inc.capabilities.membership.models import LevelMetadata, MembershipLevel

    async with factory() as uow:
        existing = (
            (
                await uow.session.execute(
                    select(MembershipLevel).where(MembershipLevel.level_key == "basic")
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            uow.session.add(
                MembershipLevel(
                    level_key="basic",
                    display_name="Basic",
                    tier_rank=1,
                    status="active",
                    cycle_days=30,
                    grant_points=100,
                    renewal_allowed=True,
                    data=LevelMetadata(values={}),
                )
            )
            await uow.commit()
            print("  basic membership level seeded")
        else:
            print("  membership level basic already exists, skipping")


async def _seed_auth_notification_templates(factory: Any) -> None:
    """Install notification capability-owned authentication templates."""

    from inc.capabilities.notification import ensure_auth_templates

    created = await ensure_auth_templates(factory)
    print(f"  authentication notification templates ensured ({created} created)")


async def _seed_oidc_clients(
    factory: Any,
    *,
    public_base_url: str,
    include_site: bool,
    site_base_url: str | None,
    site_client_secret: str | None,
    api_audience: str,
) -> None:
    from sqlalchemy import select

    from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
    from inc.capabilities.oidc_provider.clients import (
        ClientCommandContext,
        EnableClient,
        RegisterClient,
        UpdateClient,
    )
    from inc.capabilities.oidc_provider.models import OidcClient
    from inc.kernel.events import EventSchemaRegistry, OutboxWriter

    admin_base = public_base_url.rstrip("/")
    redirect_uris = [f"{admin_base}/callback"]
    post_logout_redirect_uris = [f"{admin_base}/logged-out"]
    allowed_scopes = ["openid", "profile", "email", "offline_access"]

    async with factory() as uow:
        existing = (
            (await uow.session.execute(select(OidcClient).where(OidcClient.client_id == "admin")))
            .scalars()
            .first()
        )

    sr = EventSchemaRegistry()
    sr.register(AUDIT_EVENT_KEY, AuditEntryRecorded)
    outbox = OutboxWriter(sr, SYSTEM_CLOCK)
    client_ctx = ClientCommandContext(
        uow_factory=factory,
        clock=SYSTEM_CLOCK,
        outbox=outbox,
        audit_actor_id="cli",
        audit_trace_id="install",
    )
    if existing is not None:
        if existing.client_type != "public":
            raise RuntimeError(
                "OIDC client 'admin' must remain public; refusing to repair a confidential client"
            )
        if existing.status != "active":
            await EnableClient(client_ctx)(client_id="admin")
        await UpdateClient(client_ctx)(
            client_id="admin",
            redirect_uris=redirect_uris,
            post_logout_redirect_uris=post_logout_redirect_uris,
            allowed_scopes=allowed_scopes,
            allowed_audiences=[api_audience],
        )
        print("  OIDC client 'admin' enabled and updated")
    else:
        await RegisterClient(client_ctx)(
            name="Admin SPA",
            client_type="public",
            redirect_uris=redirect_uris,
            post_logout_redirect_uris=post_logout_redirect_uris,
            allowed_scopes=allowed_scopes,
            allowed_audiences=[api_audience],
            client_id="admin",
        )
        print(f"  OIDC public client 'admin' registered (aud={api_audience})")

    if not include_site:
        return
    if site_base_url is None or site_client_secret is None:
        raise ValueError("release install requires the client URL and OIDC client secret")

    site_base = site_base_url.rstrip("/")
    async with factory() as uow:
        existing_site = (
            (
                await uow.session.execute(
                    select(OidcClient).where(OidcClient.client_id == "aiya-site")
                )
            )
            .scalars()
            .first()
        )
    site_redirect_uris = [f"{site_base}/auth/callback"]
    site_post_logout_uris = [f"{site_base}/auth/logged-out"]
    if existing_site is not None:
        if existing_site.client_type != "confidential":
            raise RuntimeError("OIDC client 'aiya-site' exists but is not confidential")
        await UpdateClient(client_ctx)(
            client_id="aiya-site",
            redirect_uris=site_redirect_uris,
            post_logout_redirect_uris=site_post_logout_uris,
            allowed_scopes=allowed_scopes,
            allowed_audiences=[api_audience],
        )
        print("  OIDC confidential client 'aiya-site' updated")
        return

    await RegisterClient(client_ctx)(
        name="User site BFF",
        client_type="confidential",
        redirect_uris=site_redirect_uris,
        post_logout_redirect_uris=site_post_logout_uris,
        allowed_scopes=allowed_scopes,
        allowed_audiences=[api_audience],
        client_id="aiya-site",
        initial_secret=site_client_secret,
    )
    print(f"  OIDC confidential client 'aiya-site' registered (aud={api_audience})")


async def _initialize_oidc_signing_key(factory: Any) -> None:
    """Create exactly one persistent active key during fresh installation."""

    from inc.adapters.oidc import FileSigningKeyStore
    from inc.capabilities.oidc_provider import KeyService
    from inc.main import _api_settings_from_env

    settings = _api_settings_from_env()
    directory = settings.oidc_signing_key_dir
    if not directory or not directory.strip():
        raise ValueError("AIYA_OIDC_SIGNING_KEY_DIR is required for release installation")
    keys = KeyService(
        uow_factory=factory,
        store=FileSigningKeyStore(directory),
        clock=SYSTEM_CLOCK,
    )
    await keys.initialize_active_key()
    print("  persistent OIDC signing key initialized")


async def _install_async(
    *,
    admin_username: str,
    admin_email: str,
    admin_password: str | None,
    public_base_url: str,
    site_base_url: str | None,
    site_client_secret: str | None,
    api_audience: str,
) -> int:
    """Seed the single release composition after migrations."""
    kernel_settings = load_settings()
    database_url = kernel_settings.database_url.get_secret_value()
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    try:
        print("[2/5] initializing OIDC signing key ...")
        await _initialize_oidc_signing_key(factory)

        print("[3/5] seeding credit points program ...")
        await _seed_points_program(factory)
        await _seed_membership_levels(factory)
        await _seed_auth_notification_templates(factory)

        print("[4/5] registering OIDC clients ...")
        await _seed_oidc_clients(
            factory,
            public_base_url=public_base_url,
            include_site=True,
            site_base_url=site_base_url,
            site_client_secret=site_client_secret,
            api_audience=api_audience,
        )

        print("[5/5] bootstrapping administrator ...")
        subject_id, generated_password = await _create_admin(
            username=admin_username,
            email=admin_email,
            password=admin_password,
            manifest=release,
        )
    finally:
        await engine.dispose()

    print()
    print("=== installation complete ===")
    print(f"  admin user       : {admin_username} ({admin_email})")
    print(f"  admin subject_id : {subject_id}")
    if generated_password is not None:
        print(f"  admin password   : {generated_password}")
    return 0


def _install_sync(
    *,
    admin_username: str,
    admin_email: str,
    admin_password: str | None,
    public_base_url: str,
    site_base_url: str | None,
    site_client_secret: str | None,
    api_audience: str,
) -> int:
    """Full empty-database installation.

    Migrations run synchronously first (alembic env.py uses its own
    asyncio.run inside so it cannot be called from a running event loop),
    then async seed steps follow.
    """
    print("=== aiya-cms release install ===")
    print()

    print("[1/5] running database migrations ...")
    _run_migrations()
    print("  migrations applied")

    return asyncio.run(
        _install_async(
            admin_username=admin_username,
            admin_email=admin_email,
            admin_password=admin_password,
            public_base_url=public_base_url,
            site_base_url=site_base_url,
            site_client_secret=site_client_secret,
            api_audience=api_audience,
        )
    )


def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _run_quality() -> int:
    """Run the static quality gates used by the Compose test profile."""

    import subprocess

    python = sys.executable
    commands: list[list[str]] = [
        [python, "-m", "ruff", "check", "."],
        [python, "-m", "ruff", "format", "--check", "."],
        [python, "-m", "mypy", "inc"],
        [python, "-m", "pip", "check"],
    ]
    for cmd in commands:
        print(f"+ {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


def _run_pytest(pytest_args: list[str]) -> int:
    """Run the pytest suite with optional passthrough arguments."""

    import subprocess

    cmd = [sys.executable, "-m", "pytest", "-q", *pytest_args]
    print(f"+ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, check=False).returncode


def _run_migration_check() -> int:
    """Downgrade to base then upgrade to head on the configured database."""

    from alembic.command import downgrade, upgrade
    from alembic.config import Config as AlembicConfig

    from inc.kernel.config import load_settings

    kernel_settings = load_settings()
    database_url = kernel_settings.database_url.get_secret_value()
    root = Path(__file__).resolve().parent.parent
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    print("downgrading to base ...")
    downgrade(cfg, "base")
    print("upgrading to head ...")
    upgrade(cfg, "head")
    print("migration check passed")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="inc.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser(
        "install",
        help="one-shot empty-database installation (migrations + seed + single admin)",
    )
    install_parser.add_argument(
        "--admin-username",
        default=_env_str("AIYA_ADMIN_USERNAME", "admin"),
        help="admin username (env: AIYA_ADMIN_USERNAME, default: admin)",
    )
    install_parser.add_argument(
        "--admin-email",
        default=_env_str("AIYA_ADMIN_EMAIL", "admin@example.com"),
        help="admin email (env: AIYA_ADMIN_EMAIL, default: admin@example.com)",
    )
    install_parser.add_argument(
        "--admin-password",
        default=_env_str("AIYA_ADMIN_PASSWORD", "") or None,
        help="admin password; AIYA_ADMIN_PASSWORD may provide one, otherwise auto-generate",
    )
    install_parser.add_argument(
        "--public-base-url",
        default=_env_str("AIYA_PUBLIC_BASE_URL", "http://127.0.0.1:8080"),
        help="admin SPA base URL for OIDC redirects (env: AIYA_PUBLIC_BASE_URL)",
    )
    install_parser.add_argument(
        "--api-audience",
        default=_env_str("AIYA_API_AUDIENCE", "aiya-admin"),
        help="API audience for OIDC access tokens (env: AIYA_API_AUDIENCE)",
    )
    install_parser.add_argument(
        "--site-base-url",
        default=_env_str("AIYA_SITE_BASE_URL", "http://127.0.0.1:4321"),
        help="Astro client base URL for OIDC redirects (env: AIYA_SITE_BASE_URL)",
    )

    subparsers.add_parser(
        "migrate",
        help="apply database migrations only (alembic upgrade head)",
    )

    subparsers.add_parser(
        "quality",
        help="run static quality gates (ruff, mypy, pip check)",
    )

    test_parser = subparsers.add_parser(
        "test",
        help="run the pytest suite",
    )
    test_parser.add_argument(
        "pytest_args",
        nargs="*",
        default=[],
        help="extra pytest arguments passed through",
    )

    subparsers.add_parser(
        "openapi-check",
        help="fail when openapi.json/openapi.sha256 drifted from the code",
    )

    subparsers.add_parser(
        "migration-check",
        help="verify migrations downgrade to base and upgrade back to head",
    )

    args = parser.parse_args()
    if args.command == "migrate":
        _run_migrations()
        print("migrations applied")
        sys.exit(0)
    if args.command == "install":
        site_client_secret = _env_str("AIYA_SITE_OIDC_CLIENT_SECRET") or None
        if site_client_secret is None or len(site_client_secret) < 32:
            parser.error(
                "AIYA_SITE_OIDC_CLIENT_SECRET must be supplied through the environment "
                "and contain at least 32 characters"
            )
        exit_code = _install_sync(
            admin_username=args.admin_username,
            admin_email=args.admin_email,
            admin_password=args.admin_password,
            public_base_url=args.public_base_url,
            site_base_url=args.site_base_url,
            site_client_secret=site_client_secret,
            api_audience=args.api_audience,
        )
        sys.exit(exit_code)
    if args.command == "quality":
        sys.exit(_run_quality())
    if args.command == "test":
        sys.exit(_run_pytest(args.pytest_args))
    if args.command == "openapi-check":
        from inc.api.openapi import check

        sys.exit(0 if check() else 1)
    if args.command == "migration-check":
        sys.exit(_run_migration_check())
    print(f"unknown command {args.command!r}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
