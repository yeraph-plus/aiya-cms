"""OpenAPI snapshot generation, admin/user projections and drift checks.

Contract source: context/spec/http-openapi.md §10.

The root ``openapi.json`` is the complete release schema used for system
validation.  ``openapi.admin.json`` and ``openapi.user.json`` are the two
client-facing projections generated from that same release manifest.
``check`` fails when any snapshot drifts.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from inc.api.config import ApiSettings
from inc.api.manifest import release

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OPENAPI_PATH = REPO_ROOT / "openapi.json"
SHA256_PATH = REPO_ROOT / "openapi.sha256"
USER_OPENAPI_PATH = REPO_ROOT / "openapi.user.json"
USER_SHA256_PATH = REPO_ROOT / "openapi.user.sha256"
ADMIN_OPENAPI_PATH = REPO_ROOT / "openapi.admin.json"
ADMIN_SHA256_PATH = REPO_ROOT / "openapi.admin.sha256"

USER_TAGS = frozenset(
    {
        "auth",
        "oidc",
        "content",
        "comments",
        "engagement",
        "discussions",
        "community-tags",
        "user-center",
        "business",
    }
)
USER_PATHS = frozenset(
    {
        "/.well-known/openid-configuration",
        "/api/v1/me",
        "/api/v1/membership/levels",
        "/api/v1/points/products",
    }
)
USER_PATH_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/me/",
    "/api/v1/posts",
    "/api/v1/pages",
    "/api/v1/works",
    "/api/v1/community/",
    "/api/v1/content/",
    "/api/v1/business/",
    "/oidc/",
)
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})
_COMPONENT_REF_PREFIX = "#/components/"
ADMIN_PATH_PREFIXES = (
    "/api/v1/admin/",
    "/healthz",
    "/api/v1/health",
    "/oidc/",
    "/.well-known/",
)


def _generate_manifest_schema(manifest: Any) -> dict[str, Any]:
    """Generate a deterministic schema without touching the database."""

    from datetime import UTC, datetime

    from inc.api.app import create_app
    from inc.kernel.time.fake import FakeClock

    class _NoopUoWFactory:
        def __call__(self) -> Any:
            raise RuntimeError("openapi generation must not touch the database")

    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    # The adapter validates that composition supplies a persistent-key path.
    # Schema construction is inert and never reads this test-only path.
    settings = ApiSettings(oidc_signing_key_dir=".tmp/openapi-oidc-keys")
    app = create_app(
        manifest=manifest,
        uow_factory=_NoopUoWFactory(),
        clock=clock,
        settings=settings,
        start_workers=False,
    )
    schema = app.openapi()
    schema.pop("servers", None)
    return schema


def generate_schema() -> dict[str, Any]:
    """Deterministic OpenAPI schema for the deployable release."""

    return _generate_manifest_schema(release)


def generate_full_schema() -> dict[str, Any]:
    """Compatibility name for the single release source schema."""

    return generate_schema()


def _component_refs(value: Any) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith(_COMPONENT_REF_PREFIX):
            parts = reference.removeprefix(_COMPONENT_REF_PREFIX).split("/", maxsplit=1)
            if len(parts) == 2:
                refs.add((parts[0], parts[1]))
        for child in value.values():
            refs.update(_component_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_component_refs(child))
    return refs


def _security_scheme_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        security = value.get("security")
        if isinstance(security, list):
            for requirement in security:
                if isinstance(requirement, dict):
                    names.update(str(name) for name in requirement)
        for child in value.values():
            names.update(_security_scheme_names(child))
    elif isinstance(value, list):
        for child in value:
            names.update(_security_scheme_names(child))
    return names


def _project_schema(
    schema: dict[str, Any],
    *,
    operation_selected: Any,
    title: str,
) -> dict[str, Any]:
    """Build a deterministic projection while retaining referenced components."""

    projected_paths: dict[str, Any] = {}
    for path, path_item in schema.get("paths", {}).items():
        selected: dict[str, Any] = {}
        for key, value in path_item.items():
            if key not in _HTTP_METHODS:
                selected[key] = deepcopy(value)
                continue
            if operation_selected(path, value):
                selected[key] = deepcopy(value)
        if any(key in _HTTP_METHODS for key in selected):
            projected_paths[path] = selected

    source_components = schema.get("components", {})
    projected_components: dict[str, dict[str, Any]] = {}
    pending = _component_refs(projected_paths)
    visited: set[tuple[str, str]] = set()
    while pending:
        category, name = pending.pop()
        if (category, name) in visited:
            continue
        try:
            component = source_components[category][name]
        except KeyError as exc:
            raise ValueError(
                f"OpenAPI projection references missing component {category}/{name}"
            ) from exc
        visited.add((category, name))
        projected_components.setdefault(category, {})[name] = deepcopy(component)
        pending.update(_component_refs(component) - visited)

    security_schemes = source_components.get("securitySchemes", {})
    for name in sorted(_security_scheme_names(projected_paths)):
        if name not in security_schemes:
            raise ValueError(f"OpenAPI projection references missing security scheme {name}")
        projected_components.setdefault("securitySchemes", {})[name] = deepcopy(
            security_schemes[name]
        )

    projected = {
        key: deepcopy(value)
        for key, value in schema.items()
        if key not in {"paths", "components", "tags", "security"}
    }
    projected_info = projected.setdefault("info", {})
    projected_info["title"] = title
    projected["paths"] = projected_paths
    if projected_components:
        projected["components"] = {
            category: dict(sorted(entries.items()))
            for category, entries in sorted(projected_components.items())
        }
    projected_tag_names = {
        tag
        for methods in projected_paths.values()
        for operation in methods.values()
        if isinstance(operation, dict)
        for tag in operation.get("tags", ())
    }
    projected["tags"] = [
        deepcopy(tag) for tag in schema.get("tags", ()) if tag.get("name") in projected_tag_names
    ]
    return projected


def project_admin_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the administrator client projection.

    The projection contains every mounted ``/api/v1/admin`` endpoint plus the
    health and OIDC protocol surfaces used by the administrator shell.  User
    content/authentication routes are intentionally excluded.
    """

    return _project_schema(
        schema,
        operation_selected=lambda path, _operation: (
            path == "/api/v1/admin" or path.startswith(ADMIN_PATH_PREFIXES)
        ),
        title="aiya-cms Admin API",
    )


def project_user_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, reference-closed user API projection."""

    return _project_schema(
        schema,
        operation_selected=lambda path, _operation: (
            (path in USER_PATHS or path.startswith(USER_PATH_PREFIXES))
            and not path.startswith("/api/v1/admin/")
            and "webhook" not in path
        ),
        title="aiya-cms User API",
    )


def generate_user_schema() -> dict[str, Any]:
    """Generate the Astro client projection from the release schema."""

    return project_user_schema(generate_full_schema())


def generate_admin_schema() -> dict[str, Any]:
    """Generate the administrator SPA projection from the release schema."""

    return project_admin_schema(generate_full_schema())


def _write_snapshot(path: Path, hash_path: Path, schema: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    hash_path.write_text(f"{digest}  {path.name}\n", encoding="utf-8")


def _snapshot_matches(path: Path, hash_path: Path, schema: dict[str, Any]) -> bool:
    expected = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != expected:
        return False
    if not hash_path.exists():
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return hash_path.read_text(encoding="utf-8").split()[0] == digest


def dump() -> Path:
    """Write full/admin/user schemas and hashes; return the full JSON path."""

    schema = generate_schema()
    _write_snapshot(OPENAPI_PATH, SHA256_PATH, schema)
    _write_snapshot(ADMIN_OPENAPI_PATH, ADMIN_SHA256_PATH, project_admin_schema(schema))
    _write_snapshot(USER_OPENAPI_PATH, USER_SHA256_PATH, project_user_schema(schema))
    return OPENAPI_PATH


def check() -> bool:
    """True when all release and client snapshot/hash pairs match current code."""

    schema = generate_schema()
    return all(
        (
            _snapshot_matches(OPENAPI_PATH, SHA256_PATH, schema),
            _snapshot_matches(
                ADMIN_OPENAPI_PATH,
                ADMIN_SHA256_PATH,
                project_admin_schema(schema),
            ),
            _snapshot_matches(USER_OPENAPI_PATH, USER_SHA256_PATH, project_user_schema(schema)),
        )
    )
