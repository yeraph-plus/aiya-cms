"""Kernel test fixtures: shared SQLite/UoW/clock fixtures live in
``tests/conftest.py``; this module only registers the test-only models."""

from __future__ import annotations

from tests.kernel._test_models import AppliedEvent  # noqa: F401  (registers test tables)
