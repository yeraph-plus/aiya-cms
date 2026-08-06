"""Runtime setting error codes."""

from inc.kernel.errors import ErrorCode

SETTING_001 = ErrorCode("SETTING_001", 404, "setting key is not registered")
SETTING_002 = ErrorCode("SETTING_002", 422, "setting value is invalid")

SETTING_CODES: tuple[ErrorCode, ...] = (SETTING_001, SETTING_002)
