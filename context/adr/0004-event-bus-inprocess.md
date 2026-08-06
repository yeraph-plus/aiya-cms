# ADR-0004: 进程内 EventBus + Cron 补偿（不引入消息队列）

- 状态: accepted
- 日期: 2026-08-02
- 决策者: 项目所有者 + AI 协作
- 关联: [kernel/events.md](../kernel/events.md)、[kernel/tasks.md](../kernel/tasks.md)、[kernel/mail.md](../kernel/mail.md)

## 背景

写路径要求"内核触发事件、监听器异步执行"（发邮件、写日志、after_save 等），并作为模块间写入解耦的唯一通道。需要确定事件投递的可靠性等级。所有者明确：不引入 Redis 消息队列和 MongoDB 持久存储的企业级方案，后期有需求再改造。

## 决策

1. **EventBus 为内核组件，纯 asyncio 进程内派发**：发布在事务提交成功后发生；每个监听器独立 `asyncio` 任务执行，单监听器失败隔离（捕获、记错误日志），不影响其他监听器与主流程。
2. **监听器显式装配**：模块在 `listeners.py` 定义监听器函数，api 层 wiring 集中 `bus.subscribe(EventType, handler)` 完成登记。禁止装饰器自动发现式的隐式注册。
3. **可靠性 = 进程内 + Cron 补偿**：普通事件（日志、计数）允许丢失；**关键异步动作要求"先落表、后执行"**（如邮件先入 `mail_outbox`，发送失败由 Cron 定期重投），以此替代 MQ 的持久化语义。
4. 事件 payload 为 Pydantic Model，事件类型名 `<domain>.<verb>`（如 `content.created`），全量在对应组件/模块文档第 8 节登记。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| Redis Stream / MQ | 投递可靠、可跨进程 | 所有者明确排除；运维与心智成本高 | 明确被否 |
| 全量 DB Outbox | 崩溃不丢任何事件 | 每张表写入都要附带 outbox 写，复杂度高 | 过度设计；关键路径用"落表+Cron"已覆盖 |
| FastAPI BackgroundTasks 裸用 | 零抽象 | 无统一失败处理、无登记处、无法测试 | 需要一个内核级统一封装 |

## 后果

### 正面
- 零额外基础设施；事件语义简单（提交后 fire-and-forget），调试容易。
- "落表+Cron"模式同时天然提供了重试记录与人工干预入口。

### 负面 / 代价
- 进程崩溃瞬间在途的普通事件丢失（接受：日志/计数类可失，关键类已落表）。
- 多实例部署时事件只在发布实例内派发（本期单实例，不构成问题）。

### 逃生门
- 后期需要跨进程/可靠投递时，EventBus 接口不变，替换实现为 Redis Stream 或 DB Outbox 投递器；监听器签名不受影响。
