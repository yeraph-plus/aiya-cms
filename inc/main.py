"""Application entry point: uvicorn target and maintenance CLI.

Contract source: context/spec/http-openapi.md §10, quality-release.md.

``python -m inc.main`` runs the single deployable ``release`` composition.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from inc.api.config import DEFAULT_ISSUER, ApiSettings, load_api_settings
from inc.api.manifest import release
from inc.kernel.config import load_settings
from inc.kernel.db import create_engine, create_session_factory

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse a boolean-like env value (1/true/yes/on) case-insensitively.

    Anything unrecognized (including "0"/"false"/empty) yields ``default``.
    This prevents truthy spellings such as ``"True"`` or ``" on "`` from
    silently disabling the Secure cookie flag outside the literal production
    gate.
    """

    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    return default


def _parse_cors_origins(value: str | None) -> tuple[str, ...]:
    """Parse the documented CSV or JSON-array CORS environment value."""

    if value is None or not value.strip():
        return ()

    raw = value.strip()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("AIYA_CORS_ORIGINS must be CSV or a JSON string array") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError("AIYA_CORS_ORIGINS JSON value must be an array of strings")
        values = parsed
    else:
        values = raw.split(",")

    return tuple(item.strip() for item in values if item.strip())


def _api_settings_from_env(environ: Mapping[str, str] | None = None) -> ApiSettings:
    """Build API settings once, with deployment keys visible in one place."""

    values = os.environ if environ is None else environ
    if values.get("AIYA_CROS_ORIGINS") and not values.get("AIYA_CORS_ORIGINS"):
        raise ValueError("AIYA_CROS_ORIGINS is not recognized; use AIYA_CORS_ORIGINS")

    environment = values.get("AIYA_ENVIRONMENT") or values.get("AIYA_ENV") or "dev"
    return load_api_settings(
        {
            "environment": environment,
            "issuer": values.get("AIYA_ISSUER") or DEFAULT_ISSUER,
            "api_audience": values.get("AIYA_API_AUDIENCE") or "aiya-admin",
            "secure_cookies": _parse_bool(values.get("AIYA_SECURE_COOKIES")),
            "cors_origins": _parse_cors_origins(values.get("AIYA_CORS_ORIGINS")),
            "trusted_proxy_cidrs": _parse_cors_origins(values.get("AIYA_TRUSTED_PROXY_CIDRS")),
            "oidc_signing_key_dir": values.get("AIYA_OIDC_SIGNING_KEY_DIR"),
            "admin_session_secret": values.get("AIYA_ADMIN_SESSION_SECRET")
            or "dev-admin-session-secret-change-me",
            "admin_session_idle_seconds": int(
                values.get("AIYA_ADMIN_SESSION_IDLE_SECONDS") or 8 * 3600
            ),
            "admin_session_absolute_seconds": int(
                values.get("AIYA_ADMIN_SESSION_ABSOLUTE_SECONDS") or 14 * 86400
            ),
            "gift_card_secret_pepper": values.get("AIYA_GIFT_CARD_SECRET_PEPPER"),
        }
    )


def _manifest_from_env(environ: Mapping[str, str] | None = None) -> Any:
    values = os.environ if environ is None else environ
    profile = (values.get("AIYA_APP_PROFILE") or "release").strip().lower()
    if profile != "release":
        raise ValueError("AIYA_APP_PROFILE must be release when specified")
    return release


def _build_app() -> Any:
    environment = os.environ.get("AIYA_ENVIRONMENT") or os.environ.get("AIYA_ENV") or "dev"
    kernel_settings = load_settings(overrides={"environment": environment})
    api_settings = _api_settings_from_env()
    engine = create_engine(kernel_settings.database_url.get_secret_value())
    session_factory = create_session_factory(engine)
    from inc.api.app import create_app
    from inc.kernel.db import SqlAlchemyUnitOfWork
    from inc.kernel.time import SYSTEM_CLOCK

    def _factory() -> Any:
        return SqlAlchemyUnitOfWork(session_factory)

    return create_app(
        manifest=_manifest_from_env(),
        uow_factory=_factory,
        clock=SYSTEM_CLOCK,
        settings=api_settings,
        redis_url=kernel_settings.redis_url.get_secret_value(),
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

    uvicorn.run(get_app(), host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
