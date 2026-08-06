"""Pipeline error-code registrations."""

from inc.kernel.errors import ErrorCode

PIPELINE_001 = ErrorCode("PIPELINE_001", 500, "Pipeline key or step is not registered")
PIPELINE_002 = ErrorCode("PIPELINE_002", 500, "Pipeline key is already registered")
PIPELINE_003 = ErrorCode("PIPELINE_003", 500, "Pipeline core step failed")

PIPELINE_CODES: tuple[ErrorCode, ...] = (PIPELINE_001, PIPELINE_002, PIPELINE_003)
