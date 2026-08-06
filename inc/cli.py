"""Explicit operational commands for database bootstrap tasks."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from pydantic import ValidationError

from inc.api.wiring import build_container
from inc.kernel.auth import RegisterRequest
from inc.kernel.config import get_settings
from inc.kernel.errors import AppError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiya-cms")
    commands = parser.add_subparsers(dest="command", required=True)
    create_admin = commands.add_parser(
        "create-admin",
        help="create the first administrator after Alembic migrations have run",
    )
    create_admin.add_argument("--username", required=True)
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument("--display-name")
    create_admin.add_argument(
        "--password",
        help="avoid this in shared shell history; omitted values are read interactively",
    )
    return parser


async def _create_admin(args: argparse.Namespace) -> int:
    password = args.password or getpass.getpass("Admin password: ")
    dto = RegisterRequest(
        username=args.username,
        email=args.email,
        password=password,
        display_name=args.display_name,
    )
    container = build_container(get_settings())
    try:
        user = await container.auth.bootstrap_admin(dto)
        await container.event_bus.wait_idle()
        print(f"created admin user {user.username} ({user.id})")
        return 0
    finally:
        await container.event_bus.wait_idle()
        close_cache = getattr(container.cache, "close", None)
        if close_cache is not None:
            await close_cache()
        await container.database.dispose()


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "create-admin":
            return asyncio.run(_create_admin(args))
    except (AppError, ValidationError) as exc:
        code = getattr(getattr(exc, "code", None), "code", None) or type(exc).__name__
        print(f"{args.command} failed: {code}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
