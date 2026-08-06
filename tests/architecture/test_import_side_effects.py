"""Guards: importing any shipped package must not register, connect or start.

Contract source: context/spec/architecture.md §8, context/spec/composition.md
§9, context/spec/kernel/boot.md §4.

Importing a package is allowed to define classes and build immutable
declarations (CapabilitySpec/FeatureSpec), but must never open connections,
start threads, mount routers, install cron jobs or mutate global registries.
These actions are reserved for the composition root and its explicit boot
phase.

The scan is AST based: only calls at module scope (not inside functions) are
considered import-time side effects.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _graph import INC_ROOT, callee_name, decorator_root, iter_source_files

FORBIDDEN_MODULE_LEVEL_CALLS = frozenset(
    {
        "Thread",
        "ThreadPoolExecutor",
        "ProcessPoolExecutor",
        "create_engine",
        "create_async_engine",
        "async_sessionmaker",
        "create_pool",
        "connect",
        "listen",
        "include_router",
        "FastAPI",
        "add_job",
        "CronTrigger",
        "create_task",
        "register",
        "subscribe",
        "publish",
        "start",
        "run",
        "launch",
        "spawn",
    }
)

FORBIDDEN_DECORATOR_ROOTS = frozenset(
    {"app", "router", "scheduler", "receiver", "cron", "task", "signal"}
)


class _SideEffectVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.in_function = 0
        self.problems: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_def(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_def(node)

    def _visit_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self.in_function == 0:
            for decorator in node.decorator_list:
                root = decorator_root(decorator)
                if root in FORBIDDEN_DECORATOR_ROOTS:
                    self.problems.append(f"{node.lineno}: module-level decorator @{root}.*")
        self.in_function += 1
        self.generic_visit(node)
        self.in_function -= 1

    def visit_Call(self, node: ast.Call) -> None:
        if self.in_function == 0:
            name = callee_name(node.func)
            if name in FORBIDDEN_MODULE_LEVEL_CALLS:
                self.problems.append(f"{node.lineno}: module-level call {name}()")
        self.generic_visit(node)


def module_level_side_effects(path: Path) -> list[str]:
    """Import-time side effects found in *path*, as human readable problems."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _SideEffectVisitor()
    visitor.visit(tree)
    return visitor.problems


def test_no_import_time_side_effects_anywhere_in_inc() -> None:
    offenders: list[str] = []
    for path in iter_source_files(INC_ROOT):
        for problem in module_level_side_effects(path):
            offenders.append(f"{path.relative_to(INC_ROOT)}:{problem}")
    assert offenders == []
