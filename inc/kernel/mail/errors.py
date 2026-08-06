"""Mail error-code registrations."""

from inc.kernel.errors import ErrorCode

MAIL_001 = ErrorCode("MAIL_001", 500, "SMTP send failed")
MAIL_002 = ErrorCode("MAIL_002", 500, "mail template is not registered")

MAIL_CODES: tuple[ErrorCode, ...] = (MAIL_001, MAIL_002)
