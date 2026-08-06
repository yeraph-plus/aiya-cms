"""G1 red tests for declaration boundaries and explicit composition-root wiring."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]


def test_kernel_content_package_exists_without_modules_imports() -> None:
    kernel_content = REPO_ROOT / "inc" / "kernel" / "content"
    if not kernel_content.is_dir():
        pytest.fail("G2 target missing: inc/kernel/content must be a first-class kernel package")

    offenders: list[str] = []
    for path in kernel_content.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "inc.modules" or name.startswith("inc.modules.") for name in names):
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_api_wiring_explicitly_registers_post_forum_and_issue() -> None:
    wiring = REPO_ROOT / "inc" / "api" / "wiring.py"
    source = wiring.read_text(encoding="utf-8")

    for type_name in ("post", "forum", "issue"):
        assert f'"{type_name}"' in source or f"'{type_name}'" in source

    assert "ContentTypeRegistry" in source
    assert ".freeze()" in source
    assert "pkgutil" not in source
    assert "importlib.metadata" not in source


def test_module_declarations_do_not_import_sibling_modules() -> None:
    modules_root = REPO_ROOT / "inc" / "modules"
    declaration_paths = [
        modules_root / "post" / "definition.py",
        modules_root / "forum" / "definition.py",
        modules_root / "issue" / "definition.py",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in declaration_paths if not path.is_file()]
    if missing:
        pytest.fail(
            "G6 target missing: explicit content declarations must exist: " + ", ".join(missing)
        )

    for path in declaration_paths:
        source = path.read_text(encoding="utf-8")
        current = path.parent.name
        for sibling in ("post", "forum", "issue"):
            if sibling != current:
                assert f"inc.modules.{sibling}" not in source
