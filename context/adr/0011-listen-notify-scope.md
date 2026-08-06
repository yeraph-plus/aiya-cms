# ADR-0011: LISTEN/NOTIFY 仅用于任务即时唤醒

- 状态: accepted
- 日期: 2026-08-02
- 决策者: 项目所有者 + AI 协作
- 关联: [kernel/tasks.md](../kernel/tasks.md)、[adr/0004-event-bus-inprocess.md](0004-event-bus-inprocess.md)

## 背景

BaseTask 状态机中，某些任务需要等待外部异步回调（典型场景：支付——下单后任务挂起，支付网关回调到达时立即继续）。朴素实现是轮询数据库，引入延迟与空转。PG 提供 LISTEN/NOTIFY 可做即时唤醒。需要明确它的使用边界，防止被滥用成第二个事件系统。

## 决策

1. **LISTEN/NOTIFY 只用于一种语义：即时唤醒等待中的任务实例**。通道唯一：`aiya_task_wakeup`，payload 为 task_instance 的 UUID。
2. 唤醒是**提示而非数据**：收到 NOTIFY 后，消费者必须回表读 `task_instances` 的真实状态再继续——NOTIFY 丢失时任务仍可由超时/兜底机制终结，语义不依赖通知送达。
3. **禁止**用 LISTEN/NOTIFY 传递业务事件、做跨进程事件总线、缓存失效广播等。事件语义一律走 EventBus（ADR-0004）。
4. kernel 在 TaskScheduler 壳内完成 LISTEN 连接管理（独立 asyncpg 连接、断线重连），对 BaseTask 子类透明；子类只需调用 `await self.wait_wakeup(...)`。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| 轮询 task_instances | 零额外机制 | 延迟与空转；支付体验差 | 所有者明确避免长轮询 |
| LISTEN/NOTIFY 通用化（当总线用） | 看起来"顺手" | PG 通知不持久、无重放、payload 有 8KB 限制、消费者语义混乱 | 明确限定单一语义防止失控 |
| Redis Pub/Sub | 表达力类似 | 多一个依赖才能做的事 PG 已能做 | 保持最小依赖 |

## 后果

### 正面
- 支付类场景的等待延迟从轮询间隔级降到毫秒级。
- 语义单一，代码里出现 LISTEN/NOTIFY 就只有一种读法。

### 负面 / 代价
- NOTIFY 不持久：监听方断线期间的通知丢失——由"提示而非数据 + 超时兜底"设计对冲。

### 逃生门
- 后期需要可靠唤醒（断线补发）：在 task_instances 上加 `wakeup_requested_at` 列，监听器启动时补扫；不改动子类 API。
