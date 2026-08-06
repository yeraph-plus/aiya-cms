"""AST helpers shared by architecture guard tests.

All guards are static: they run without third-party imports and without
importing the application, so they can gate a partially built repo.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
INC_ROOT = REPO_ROOT / "inc"
PACKAGE = "inc"


def iter_source_files(root: Path) -> list[Path]:
    """All python files under *root*, skipping caches and hidden dirs."""

    return sorted(
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and not any(part.startswith(".") for part in p.parts)
    )


def module_name(path: Path, root: Path = INC_ROOT, package: str = PACKAGE) -> str:
    """Dotted module name of *path* relative to *root*."""

    parts = list(path.relative_to(root).parts)
    parts[-1] = parts[-1][:-3] if parts[-1] != "__init__.py" else ""
    if not parts[-1]:
        parts = parts[:-1]
    return f"{package}.{'.'.join(parts)}" if parts else package


def first_party_imports(path: Path, root: Path = INC_ROOT, package: str = PACKAGE) -> set[str]:
    """Fully qualified first-party module names imported by *path*.

    Relative imports are resolved against the importing module. Imported
    symbols re-exported under a different alias are still detected through
    the module-level ``import`` statement.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _remember(imports, alias.name, package)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.level == 0:
                _remember(imports, node.module, package)
            else:
                base = module_name(path, root, package).split(".")[:-1]
                depth = node.level - 1
                if depth <= len(base):
                    target = ".".join(base[: len(base) - depth] + node.module.split("."))
                    _remember(imports, target, package)
    return imports


def _remember(imports: set[str], name: str, package: str) -> None:
    if name == package or name.startswith(f"{package}."):
        imports.add(name)


def callee_name(node: ast.AST) -> str | None:
    """Simple callable name: ``Name.id`` or final ``Attribute.attr``."""

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def decorator_root(node: ast.AST) -> str | None:
    """Root of a decorator expression, e.g. ``app`` for ``@app.post(...)``."""

    if isinstance(node, ast.Call):
        node = node.func
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    return None
