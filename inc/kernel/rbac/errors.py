"""RBAC error-code registration."""

from inc.kernel.errors import ErrorCode

RBAC_001 = ErrorCode("RBAC_001", 403, "缺少能力别名")
RBAC_002 = ErrorCode("RBAC_002", 404, "角色不存在")
RBAC_003 = ErrorCode("RBAC_003", 500, "能力别名未登记")
RBAC_004 = ErrorCode("RBAC_004", 409, "不能替换当前用户角色")

RBAC_CODES: tuple[ErrorCode, ...] = (RBAC_001, RBAC_002, RBAC_003, RBAC_004)
