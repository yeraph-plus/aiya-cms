"""Task error-code registrations."""

from inc.kernel.errors import ErrorCode

TASK_001 = ErrorCode("TASK_001", 500, "任务类型未登记或注册无效")
TASK_002 = ErrorCode("TASK_002", 409, "任务状态转换非法")
TASK_003 = ErrorCode("TASK_003", 504, "任务执行超时")
TASK_004 = ErrorCode("TASK_004", 404, "任务实例不存在")

TASK_CODES: tuple[ErrorCode, ...] = (TASK_001, TASK_002, TASK_003, TASK_004)
