"""Red-line guards: Session, raw SQL, JSONB, time and money conventions.

Contract source: context/spec/architecture.md §6/§9, context/spec/kernel/database.md
§1/§8, context/spec/quality-release.md §2.1.

- Session/engine creation only inside ``inc/kernel/db``.
- Raw SQL only inside ``alembic`` (and approved isolated infrastructure).
- JSONB only through the kernel ``JsonBModel`` wrapper.
- Business layers never construct naive datetimes; the kernel Clock owns time.
- Business capabilities never declare ``Float`` columns (money is integer
  minor units, points are integers).
"""

from __future__ import annotations

import re
from pathlib import Path

from _graph import INC_ROOT, iter_source_files

_SESSION_SYMBOLS = (
    "async_sessionmaker",
    "create_async_engine",
    "AsyncSession",
    "AsyncEngine",
)

# asyncpg may legitimately appear in connection URLs; only flag real driver
# usage (attribute access or imports).
_ASYNCPG_PATTERNS = (r"\basyncpg\.", r"\bimport asyncpg\b")

_RAW_SQL_PATTERNS = (r"\btext\(", r"\.execute\(\s*['\"]")

_NAIVE_DATETIME_PATTERNS = (r"\butcnow\(", r"\bdatetime\.now\(", r"\bdate\.today\(")

_BUSINESS_LAYERS = ("capabilities", "features", "api")


def _scan(root: Path, patterns: tuple[str, ...]) -> list[str]:
    offenders: list[str] = []
    for path in iter_source_files(root):
        source = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if re.search(pattern, source):
                offenders.append(f"{path}: {pattern}")
    return offenders


def test_session_creation_confined_to_kernel_db() -> None:
    allowed_prefix = str(INC_ROOT / "kernel" / "db")
    offenders: list[str] = []
    for path in iter_source_files(INC_ROOT):
        if str(path).startswith(allowed_prefix):
            continue
        source = path.read_text(encoding="utf-8")
        for symbol in _SESSION_SYMBOLS:
            if re.search(rf"\b{symbol}\b", source):
                offenders.append(f"{path}: {symbol}")
        for pattern in _ASYNCPG_PATTERNS:
            if re.search(pattern, source):
                offenders.append(f"{path}: asyncpg")
    assert offenders == []


def test_raw_sql_confined_to_alembic() -> None:
    assert _scan(INC_ROOT, _RAW_SQL_PATTERNS) == []


def test_jsonb_always_bound_to_pydantic_model() -> None:
    offenders: list[str] = []
    for layer in _BUSINESS_LAYERS:
        for path in iter_source_files(INC_ROOT / layer):
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if "JSONB" in line and "JsonBModel" not in line:
                    offenders.append(f"{path}:{lineno}: JSONB without JsonBModel")
    assert offenders == []


def test_no_naive_datetime_in_business_layers() -> None:
    for layer in _BUSINESS_LAYERS:
        assert _scan(INC_ROOT / layer, _NAIVE_DATETIME_PATTERNS) == []


def test_no_float_money_columns_in_capabilities() -> None:
    assert _scan(INC_ROOT / "capabilities", (r"\bFloat\(",)) == []
