"""Taxonomy kernel error-code registration."""

from inc.kernel.errors import ErrorCode

TERM_001 = ErrorCode("TERM_001", 404, "taxonomy term not found")
TERM_002 = ErrorCode("TERM_002", 422, "taxonomy group is not declared for content type")
TERM_003 = ErrorCode("TERM_003", 409, "taxonomy term slug conflicts")
TERM_004 = ErrorCode("TERM_004", 422, "taxonomy term does not match content type")
TERM_005 = ErrorCode("TERM_005", 404, "content type is not registered")

TERM_CODES: tuple[ErrorCode, ...] = (TERM_001, TERM_002, TERM_003, TERM_004, TERM_005)
