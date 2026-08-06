"""EventBus error-code registration."""

from inc.kernel.errors import ErrorCode

EVENT_001 = ErrorCode("EVENT_001", 500, "事件类型未登记或总线已冻结")
EVENT_CODES: tuple[ErrorCode, ...] = (EVENT_001,)
