# Kernel / logging

## 1. 设计目的

统一结构化日志：全系统一个初始化入口、一个获取入口；请求级 `request_id` 贯穿；缓存命中/未命中等基础设施日志在 kernel 封装内部完成（调用方无感）。

非目标：审计不是日志——审计走 [audit.md](audit.md) 落库；日志清理不由本组件负责（无文件轮转之外的清理需求，stdout 为主）。

## 2. 范围与依赖

- 代码位置: `inc/kernel/logging.py`
- 依赖的 kernel 组件: config
- 被谁依赖: 全部组件
- 外部依赖: structlog（stdlib logging 集成）

## 3. 领域模型

- `setup_logging(settings)`：应用启动时调用一次；dev 输出彩色控制台，prod/test 输出 JSON 行。
- `get_logger(name)` → structlog BoundLogger。
- 上下文变量：`request_id`（api 中间件写入）、`principal_id`（认证后写入），自动并入每条日志。

## 4. 状态机

无。

## 5. 数据库

无（日志输出 stdout，由部署环境收集）。

## 6. 公开 API

```python
def setup_logging(settings: Settings) -> None
def get_logger(name: str) -> structlog.stdlib.BoundLogger
def bind_context(**kv) -> None  # request_id / principal_id 等
```

### HTTP API

无。

## 7. Pipeline

无。

## 8. Event

无。

## 9. 错误码

无（日志组件自身失败不阻断主流程，降级 stdlib 默认配置）。

## 10. Cron / 任务

无。

## 11. 测试边界

- prod 模式输出为合法 JSON 行，含 `level/event/timestamp`。
- bind_context 后日志携带 request_id。
- 日志初始化重复调用幂等（不重复加 handler）。

## 12. 未决事项

无。
