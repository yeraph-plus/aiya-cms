"""Freeze and verify the FastAPI OpenAPI contract (ADR-0016)."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from inc.kernel.config import Settings

from .app import create_app

DEFAULT_OUTPUT = Path(__file__).parents[2] / "openapi.json"


def _canonical_bytes(schema: dict[str, object]) -> bytes:
    return json.dumps(schema, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(schema: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(schema)).hexdigest()


def dump(path: Path = DEFAULT_OUTPUT) -> None:
    application = create_app(
        Settings(_env_file=None, env="test", cache_backend="memory")  # type: ignore[call-arg]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = application.openapi()
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.with_suffix(".sha256").write_text(_digest(schema) + "\n", encoding="utf-8")


def check(path: Path = DEFAULT_OUTPUT) -> bool:
    if not path.exists():
        return False
    application = create_app(
        Settings(_env_file=None, env="test", cache_backend="memory")  # type: ignore[call-arg]
    )
    schema = application.openapi()
    expected = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    digest_path = path.with_suffix(".sha256")
    return (
        path.read_text(encoding="utf-8") == expected
        and digest_path.exists()
        and digest_path.read_text(encoding="utf-8").strip() == _digest(schema)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dump", "check"))
    parser.add_argument("--path", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.command == "dump":
        dump(args.path)
        return 0
    return 0 if check(args.path) else 1


if __name__ == "__main__":
    raise SystemExit(main())
