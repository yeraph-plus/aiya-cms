"""Application entry point: uvicorn target and maintenance CLI.

Contract source: context/spec/http-openapi.md §10, quality-release.md.

``python -m inc.main`` runs the uvicorn server on the full product
manifest; subcommands ``openapi-dump`` and ``openapi-check`` manage the
frozen HTTP contract.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from inc.api.config import load_api_settings
from inc.api.manifest import cms
from inc.kernel.config import load_settings
from inc.kernel.db import create_engine, create_session_factory

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _build_app() -> Any:
    kernel_settings = load_settings()
    api_settings = load_api_settings(
        {
            "issuer": "http://localhost:8080",
            "api_audience": "aiya-admin",
        }
    )
    engine = create_engine(kernel_settings.database_url.get_secret_value())
    session_factory = create_session_factory(engine)
    from inc.api.app import create_app
    from inc.kernel.db import SqlAlchemyUnitOfWork
    from inc.kernel.time import SYSTEM_CLOCK

    def _factory() -> Any:
        return SqlAlchemyUnitOfWork(session_factory)

    return create_app(
        manifest=cms,
        uow_factory=_factory,
        clock=SYSTEM_CLOCK,
        settings=api_settings,
    )


_app: Any | None = None


def get_app() -> Any:
    """Lazy app for uvicorn's ``inc.main:get_app`` factory."""

    global _app
    if _app is None:
        _app = _build_app()
    return _app


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if command == "openapi-dump":
        from inc.api.openapi import dump

        path = dump()
        print(f"wrote {path}")
        return
    if command == "openapi-check":
        from inc.api.openapi import check

        sys.exit(0 if check() else 1)
    if command != "serve":
        print(f"unknown command {command!r}; use serve|openapi-dump|openapi-check", file=sys.stderr)
        sys.exit(2)
    import uvicorn

    uvicorn.run(get_app(), host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
