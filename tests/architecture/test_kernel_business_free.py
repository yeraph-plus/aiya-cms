"""Guards: kernel source stays free of business vocabulary.

Contract source: context/spec/architecture.md §11, context/spec/kernel/README.md.

The kernel owns technical runtime mechanisms only. A business identifier
(User, Content, OidcClient, PointAccount, ...) appearing in kernel source is
the first symptom of a domain model leaking back into the kernel.

Scanning only AST identifiers (names, attributes, defs) avoids false
positives from docstrings and prose comments.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _graph import INC_ROOT, iter_source_files

BUSINESS_PREFIXES = (
    "user",
    "identity",
    "oidc",
    "role",
    "permission",
    "rbac",
    "content",
    "taxonomy",
    "comment",
    "notification",
    "mail",
    "email",
    "points",
    "payment",
    "purchase",
    "check_in",
    "asset",
    "forum",
    "interaction",
    "organization",
    "membership",
    "reward",
    "coupon",
    "review",
)


def _identifiers(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.append(node.id)
        elif isinstance(node, ast.Attribute):
            found.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.append(node.name)
    return found


def test_kernel_has_no_business_identifiers() -> None:
    offenders: list[str] = []
    for path in iter_source_files(INC_ROOT / "kernel"):
        for identifier in _identifiers(path):
            lowered = identifier.lower()
            if any(lowered.startswith(prefix) for prefix in BUSINESS_PREFIXES):
                offenders.append(f"{path}: business identifier {identifier!r}")
    assert offenders == []


def test_kernel_has_no_business_table_declarations() -> None:
    offenders: list[str] = []
    for path in iter_source_files(INC_ROOT / "kernel"):
        source = path.read_text(encoding="utf-8")
        for line in source.splitlines():
            marker = "__tablename__"
            if marker not in line:
                continue
            tail = line.split(marker, 1)[1]
            if "=" not in tail:
                continue
            name = tail.split("=", 1)[1].strip().strip("\"'")
            if any(name.startswith(prefix) for prefix in BUSINESS_PREFIXES):
                offenders.append(f"{path}: business table {name!r}")
    assert offenders == []
