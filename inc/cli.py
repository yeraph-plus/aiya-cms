"""Operations CLI.

Contract source: context/spec/access.md §4 (ops-only bootstrap), quality-release.md.

``python -m inc.cli create-admin --username admin --email admin@example.com``
registers a local user (idempotently) and grants the bootstrap
administrator role. The password is generated when not provided and
printed exactly once.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
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

        generated = password is None
        effective_password = password or secrets.token_urlsafe(18)

        identity_ctx = IdentityCommandContext(
            uow_factory=factory,
            clock=SYSTEM_CLOCK,
            hasher=services.hasher,
            outbox=services.outbox,
            audit_actor_id="cli",
            audit_trace_id="create-admin",
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

        access_ctx = AccessCommandContext(
            uow_factory=factory,
            clock=SYSTEM_CLOCK,
            outbox=services.outbox,
            permissions=services.permission_registry,
            subject_exists=_subject_exists(services.identity_queries),
            audit_actor_id="cli",
            audit_trace_id="create-admin",
        )
        await BootstrapAdministrator(access_ctx)(subject_type="identity", subject_id=subject_id)
        return subject_id, effective_password if generated else None
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="inc.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    admin_parser = subparsers.add_parser("create-admin", help="bootstrap the admin user")
    admin_parser.add_argument("--username", required=True)
    admin_parser.add_argument("--email", required=True)
    admin_parser.add_argument("--password", default=None, help="omit to generate one")

    args = parser.parse_args()
    if args.command == "create-admin":
        subject_id, generated_password = asyncio.run(
            _create_admin(username=args.username, email=args.email, password=args.password)
        )
        print(f"admin ready: subject={subject_id}")
        if generated_password is not None:
            print(f"generated password (shown once): {generated_password}")
        return
    print(f"unknown command {args.command!r}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
