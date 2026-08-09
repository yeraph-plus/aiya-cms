"""Operations CLI.

Contract source: context/spec/access.md §4/§9 (single super admin bootstrap),
quality-release.md.

``python -m inc.cli migrate`` applies database migrations only (the single
Compose entry for running ``alembic upgrade head``). ``python -m inc.cli
install`` is the one-shot empty-database installation and the only path that
creates the super administrator. In a single run it:
applies migrations, seeds the default points program, registers the admin
OIDC client, and bootstraps the single administrator user (creating the
account and binding the ``administrator`` role). The password is generated
when not provided and printed exactly once. Re-running is safe for the same
administrator but refuses to create a second one (``access.administrator_exists``).

All database/redis/server configuration is read from environment variables
(AIYA_DATABASE_URL, AIYA_REDIS_URL, AIYA_PUBLIC_BASE_URL, AIYA_API_AUDIENCE,
etc.). There is no separate bootstrap subcommand, no CLI password recovery,
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

from inc.api.config import load_api_settings
from inc.api.manifest import cms
from inc.capabilities.access import (
    BootstrapAdministrator,
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
    *, username: str, email: str, password: str | None
) -> tuple[str, str | None]:
    from inc.api.container import build_container

    factory, engine = _build_factory()
    try:
        container = build_container(
            manifest=cms,
            uow_factory=factory,
            clock=SYSTEM_CLOCK,
            settings=load_api_settings(),
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

    from inc.capabilities.points.models import PointsProgram

    async with factory() as uow:
        existing = (
            (
                await uow.session.execute(
                    select(PointsProgram).where(PointsProgram.program_key == "default")
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            print("  points program default already exists, skipping")
            return
        uow.session.add(
            PointsProgram(
                program_key="default",
                display_name="Default",
                unit="points",
                status="active",
                allow_admin_reversal=True,
            )
        )
        await uow.commit()
    print("  default points program seeded")


async def _seed_oidc_clients(factory: Any, *, public_base_url: str, api_audience: str) -> None:
    from sqlalchemy import select

    from inc.capabilities.audit.schemas import AUDIT_EVENT_KEY, AuditEntryRecorded
    from inc.capabilities.oidc_provider.clients import (
        ClientCommandContext,
        RegisterClient,
    )
    from inc.capabilities.oidc_provider.models import OidcClient
    from inc.kernel.events import EventSchemaRegistry, OutboxWriter

    async with factory() as uow:
        existing = (
            (await uow.session.execute(select(OidcClient).where(OidcClient.client_id == "admin")))
            .scalars()
            .first()
        )
    if existing is not None:
        print("  OIDC client 'admin' already exists, skipping")
        return

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
    base = public_base_url.rstrip("/")
    await RegisterClient(client_ctx)(
        name="Admin SPA",
        client_type="public",
        redirect_uris=[f"{base}/callback"],
        post_logout_redirect_uris=[f"{base}/logged-out"],
        allowed_scopes=["openid", "profile", "email", "offline_access"],
        allowed_audiences=[api_audience],
        client_id="admin",
    )
    print(f"  OIDC public client 'admin' registered (aud={api_audience})")


async def _install_async(
    *,
    admin_username: str,
    admin_email: str,
    admin_password: str | None,
    public_base_url: str,
    api_audience: str,
) -> int:
    """Seed steps (points program, OIDC clients, admin) after migrations."""
    kernel_settings = load_settings()
    database_url = kernel_settings.database_url.get_secret_value()
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    try:
        print("[2/4] seeding default points program ...")
        await _seed_points_program(factory)

        print("[3/4] registering OIDC clients ...")
        await _seed_oidc_clients(
            factory, public_base_url=public_base_url, api_audience=api_audience
        )

        print("[4/4] bootstrapping administrator ...")
        subject_id, generated_password = await _create_admin(
            username=admin_username,
            email=admin_email,
            password=admin_password,
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
    api_audience: str,
) -> int:
    """Full empty-database installation.

    Migrations run synchronously first (alembic env.py uses its own
    asyncio.run inside so it cannot be called from a running event loop),
    then async seed steps follow.
    """
    print("=== aiya-cms install ===")
    print()

    print("[1/4] running database migrations ...")
    _run_migrations()
    print("  migrations applied")

    return asyncio.run(
        _install_async(
            admin_username=admin_username,
            admin_email=admin_email,
            admin_password=admin_password,
            public_base_url=public_base_url,
            api_audience=api_audience,
        )
    )


def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _run_quality() -> int:
    """Run the static quality gates used by the Compose test profile."""

    import subprocess

    commands: list[list[str]] = [
        ["python", "-m", "ruff", "check", "."],
        ["python", "-m", "ruff", "format", "--check", "."],
        ["python", "-m", "mypy", "inc"],
        ["python", "-m", "pip", "check"],
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

    cmd = ["python", "-m", "pytest", "-q", *pytest_args]
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
        default=None,
        help="admin password; omit to auto-generate one",
    )
    install_parser.add_argument(
        "--public-base-url",
        default=_env_str("AIYA_PUBLIC_BASE_URL", "http://127.0.0.1:7000"),
        help="admin SPA base URL for OIDC redirects (env: AIYA_PUBLIC_BASE_URL)",
    )
    install_parser.add_argument(
        "--api-audience",
        default=_env_str("AIYA_API_AUDIENCE", "aiya-admin"),
        help="API audience for OIDC access tokens (env: AIYA_API_AUDIENCE)",
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
        exit_code = _install_sync(
            admin_username=args.admin_username,
            admin_email=args.admin_email,
            admin_password=args.admin_password,
            public_base_url=args.public_base_url,
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
