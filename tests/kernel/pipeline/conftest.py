"""Pipeline registry fixtures."""

import pytest

from inc.kernel.errors import COMMON_CODES, clear_registry, register_error_codes
from inc.kernel.pipeline import PIPELINE_CODES


@pytest.fixture(autouse=True)
def register_pipeline_codes() -> None:
    clear_registry()
    register_error_codes(*COMMON_CODES, *PIPELINE_CODES)
