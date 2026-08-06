# ADR-0021: EventBus 实现与装配生命周期

- 状态: accepted
- 日期: 2026-08-04
- 关联: [kernel/events.md](../kernel/events.md)、[ADR-0004](0004-event-bus-inprocess.md)

## 决策

1. `Event` 使用 Pydantic payload；事件类型先经全局显式登记表注册，`EventBus` 只接受已登记类型。
2. `subscribe` 只允许在 wiring 装配阶段调用；`freeze()` 后注册表关闭，运行期订阅统一映射 `EVENT_001`。
3. `publish` 为同步调度入口，逐个 handler 创建独立 asyncio Task；调用方不等待 handler，`wait_idle()` 仅用于测试和优雅停机。
4. handler 异常在任务边界捕获并记录事件类型、handler 名和 request_id；异常不传播到其他 handler 或发布方。
5. `get_event_bus()` 提供进程单例，`fresh_event_bus()` 创建隔离实例供测试和独立 wiring 使用。

## 后果

- 普通事件仍是进程内 fire-and-forget，关键动作必须先落表再由 Cron 补偿。
- 显式登记和 freeze 让事件清单在启动时可审计，但模块 wiring 必须按顺序执行。
