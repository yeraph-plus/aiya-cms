"""G8 guard: migrated CMS capabilities must not retain duplicate modules."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
LEGACY_IMPORT = re.compile(r"(?:from|import) inc\.modules\.(?:content|taxonomy|comment)")


def test_legacy_cms_module_directories_are_removed() -> None:
    modules_root = REPO_ROOT / "inc" / "modules"
    for name in ("content", "taxonomy", "comment"):
        assert not (modules_root / name).exists(), name


def test_no_source_imports_legacy_cms_modules() -> None:
    for root in (REPO_ROOT / "inc", REPO_ROOT / "tests"):
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert LEGACY_IMPORT.search(source) is None, path


def test_kernel_packages_do_not_export_legacy_registries() -> None:
    import inc.kernel.comment as comment
    import inc.kernel.content as content

    assert not hasattr(content, "content_type_registry")
    assert not hasattr(content, "register_content_type")
    assert not hasattr(comment, "comment_target_registry")
    assert not hasattr(comment, "register_comment_target")
    assert not (REPO_ROOT / "inc" / "kernel" / "comment" / "registry.py").exists()
