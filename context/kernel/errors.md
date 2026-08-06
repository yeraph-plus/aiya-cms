# Kernel / errors

## 1. 设计目的

统一异常体系与错误码登记处：所有业务错误以 `AppError(code, ...)` 抛出，全局异常处理器输出一致的错误响应；错误码**先登记后使用**，未登记的码在启动时 fail-fast。

非目标：不处理非业务异常（未捕获异常统一兜底为 COMMON_500 并记日志）。

## 2. 范围与依赖

- 代码位置: `inc/kernel/errors/`
- 依赖的 kernel 组件: config
- 被谁依赖: 全部组件、全部模块
- 外部依赖: fastapi（异常处理器）

## 3. 领域模型

- `ErrorCode`：值对象 `(code: str, http_status: int, message_template: str)`。命名 `DOMAIN_NNN`，DOMAIN 大写段（COMMON/CONFIG/DB/AUTH/RBAC/USER/SETTING/PIPELINE/EVENT/TASK/CACHE/MAIL/CONTENT/TERM/COMMENT…模块自定自己的段）。
- `ErrorRegistry`：登记处，重复登记或码冲突即报错。
- `AppError(Exception)`：`(code: ErrorCode, *, detail: dict | None, cause: Exception | None)`。构造时校验 code 已登记，未登记即抛 `ValueError`（使用点 fail-fast）。
- 错误响应 DTO：`ErrorResponse{code: str, message: str, detail: dict | None, request_id: str}`。

## 4. 状态机

无。

## 5. 数据库

无（错误码登记在代码 + 文档，权限表 seed 类似机制；不入库）。

JSONB 字段对应的 Pydantic Model: 无。

## 6. 公开 API

```python
class AppError(Exception): ...
class ErrorCode: ...                      # 值对象
def register_error_codes(*codes: ErrorCode) -> None
def validate_registry(required: Iterable[ErrorCode]) -> None  # wiring fail-fast：缺失即报错
def clear_registry() -> None              # 测试与重启装配用
async def app_error_handler(request, exc: AppError) -> JSONResponse  # 全局处理器
async def unhandled_exception_handler(request, exc: Exception) -> JSONResponse  # COMMON_500 兜底
async def request_validation_handler(request, exc: RequestValidationError) -> JSONResponse  # COMMON_001
```

kernel 通用码（各组件私有码见各自文档）：

| 错误码 | HTTP | 含义 |
|---|---|---|
| COMMON_001 | 422 | 请求参数校验失败（Pydantic 包装） |
| COMMON_403 | 403 | 权限不足（兜底） |
| COMMON_404 | 404 | 资源不存在（兜底） |
| COMMON_409 | 409 | 状态冲突（兜底） |
| COMMON_429 | 429 | 请求频率超限 |
| COMMON_500 | 500 | 内部错误（未捕获异常兜底） |

### HTTP API

无。

## 7. Pipeline

无。

## 8. Event

无。

## 9. 错误码

组件自身码即上表 COMMON_* 与 CONFIG_001（config.md）。

## 10. Cron / 任务

无。

## 11. 测试边界

- 重复登记同一 code 字符串 → 报错。
- 抛出已登记 AppError → 响应体含 `code/http_status/message/request_id`，HTTP 状态与登记一致。
- 使用未登记 code 构造 AppError → 立即失败；`validate_registry(required)` 对缺失码 fail-fast（wiring 完整性测试覆盖）。
- 未捕获异常 → COMMON_500，响应不泄露堆栈，日志含堆栈与 request_id。
- Pydantic ValidationError → COMMON_001，detail 含字段错误列表且始终可 JSON 序列化。

## 12. 未决事项

- 错误 message 的 i18n（本期仅中文 message 模板）。
