"""OpenAPI snapshot generation and drift checks.

Contract source: context/spec/http-openapi.md §10.

The root ``openapi.json`` and ``openapi.sha256`` are generated
deterministically from the full product manifest; ``check`` fails when the
files drifted from the code.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from inc.api.config import ApiSettings
from inc.api.manifest import cms

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OPENAPI_PATH = REPO_ROOT / "openapi.json"
SHA256_PATH = REPO_ROOT / "openapi.sha256"


def generate_schema() -> dict[str, Any]:
    """Deterministic OpenAPI schema for the full product manifest."""

    from datetime import UTC, datetime

    from inc.api.app import create_app
    from inc.kernel.time.fake import FakeClock

    class _NoopUoWFactory:
        def __call__(self) -> Any:
            raise RuntimeError("openapi generation must not touch the database")

    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    settings = ApiSettings()
    app = create_app(
        manifest=cms,
        uow_factory=_NoopUoWFactory(),
        clock=clock,
        settings=settings,
        start_workers=False,
    )
    schema = app.openapi()
    schema.pop("servers", None)
    return schema


def dump() -> Path:
    """Write openapi.json and openapi.sha256; returns the JSON path."""

    schema = generate_schema()
    OPENAPI_PATH.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(OPENAPI_PATH.read_bytes()).hexdigest()
    SHA256_PATH.write_text(f"{digest}  openapi.json\n", encoding="utf-8")
    return OPENAPI_PATH


def check() -> bool:
    """True when both snapshot files match the current code."""

    schema = generate_schema()
    expected = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not OPENAPI_PATH.exists():
        return False
    if OPENAPI_PATH.read_text(encoding="utf-8") != expected:
        return False
    if not SHA256_PATH.exists():
        return False
    digest = hashlib.sha256(OPENAPI_PATH.read_bytes()).hexdigest()
    return SHA256_PATH.read_text(encoding="utf-8").split()[0] == digest
