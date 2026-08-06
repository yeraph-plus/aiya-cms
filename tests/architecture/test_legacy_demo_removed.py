"""Guards: old demo structure, migrations and bindings are gone for good.

Contract source: context/full-rebuild-plan.md §12 (deletion list),
context/spec/kernel/database.md §7.

The old demo had no compatibility obligations. Its directories, revisions
and bindings must not silently return; the archive entry point is the
``demo-before-full-rebuild`` git tag.
"""

from __future__ import annotations

import re
from pathlib import Path

from _graph import INC_ROOT, REPO_ROOT, iter_source_files

LEGACY_KERNEL_DIRS = (
    "identity",
    "auth",
    "rbac",
    "content",
    "taxonomy",
    "comment",
    "mail",
    "settings",
    "audit",
    "pipeline",
)

LEGACY_API_FILES = ("routes.py", "deps.py", "wiring.py")

OLD_MIGRATION_NAMES = (
    "0001_m0_empty",
    "0002_identity",
    "0003_rbac",
    "0004_auth",
    "0005_tasks",
    "0006_mail_audit_settings",
    "0007_m2_modules",
    "0008_content_interactions",
    "0009_password_reset",
    "0010_declarative_content_columns",
)

LEGACY_IMPORT = re.compile(
    r"(?:from|import) inc\.(?:"
    r"modules|"
    r"kernel\.(?:identity|auth|rbac|content|taxonomy|comment|mail|settings|audit|pipeline)"
    r")(?:\.[\w.]+)?"
)


def test_modules_layer_is_gone() -> None:
    assert not (INC_ROOT / "modules").exists()


def test_old_kernel_business_dirs_are_gone() -> None:
    for name in LEGACY_KERNEL_DIRS:
        assert not (INC_ROOT / "kernel" / name).exists(), f"inc/kernel/{name} must not return"


def test_old_api_binding_files_are_gone() -> None:
    for name in LEGACY_API_FILES:
        assert not (INC_ROOT / "api" / name).exists(), f"inc/api/{name} must not return"


def test_root_cli_and_settings_facades_are_gone() -> None:
    assert not (INC_ROOT / "cli.py").exists()
    assert not (INC_ROOT / "setting.py").exists()


def test_old_migration_revisions_are_gone() -> None:
    versions = REPO_ROOT / "alembic" / "versions"
    stale = [name for name in OLD_MIGRATION_NAMES if (versions / f"{name}.py").exists()]
    assert stale == []


def test_no_source_imports_legacy_paths() -> None:
    for root in (INC_ROOT, REPO_ROOT / "tests"):
        for path in iter_source_files(root):
            assert LEGACY_IMPORT.search(path.read_text(encoding="utf-8")) is None, path
