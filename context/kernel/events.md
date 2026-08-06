# Kernel / events（EventBus）

## 1. 设计目的

进程内异步事件总线（ADR-0004）：写路径提交后派发领域事件；监听器异步执行（发邮件、写审计、更新计数）；**跨模块写入的唯一合法通道**。

非目标：不做持久化/重放的事件溯源；不做跨进程投递（逃生门见 ADR-0004）。

## 2. 范围与依赖

- 代码位置: `inc/kernel/events/`
- 依赖的 kernel 组件: errors, logging
- 被谁依赖: pipeline（执行器提交后发布）, auth, identity, settings, tasks, mail, kernel content/taxonomy/comment, 全部 modules
- 外部依赖: 无新增

## 3. 领域模型

- `Event(BaseModel)`：`type: str`（`<domain>.<verb>`）、`payload: BaseModel`、`occurred_at: datetime`、`actor_id: UUID | None`。
- `EventBus`：
  - `subscribe(event_type: str, handler: Handler)`——仅在 wiring 装配期调用；运行期调用报错。
  - `publish(event: Event)`——同步收集 handlers，逐一手动 `asyncio` 任务派发；**单 handler 失败隔离**（捕获异常记 error 日志，含 event.type/handler 名/request_id），不影响其他 handler 与调用方。
  - `wait_idle()`——测试用：等待所有在途 handler 完成。
- Handler 签名：`async def handler(event: Event) -> None`。handler 内需要写库时自开 UoW（此时原事务已提交）。
- 关键异步动作纪律：允许丢失的事件直接监听；**不允许丢失的先落表后处理**（邮件模式见 mail.md）。

## 4. 状态机

无。

## 5. 数据库

无。

## 6. 公开 API

```python
class Event(BaseModel): ...
class EventBus: ...
def get_event_bus() -> EventBus  # 单例；测试用 fresh_event_bus()
```

### HTTP API

无。

## 7. Pipeline

无（events 被 pipeline 使用，反向禁止）。

## 8. Event

本组件即事件基础设施。内核事件清单见 [00-kernel-overview.md](00-kernel-overview.md) 第 5 节；Content/Taxonomy/Comment 事件在各自 kernel 规格第 8 节登记；业务模块事件在各自 module 文档第 8 节登记。

事件命名规则：`<domain>.<verb>` 全小写；payload 必须为独立 Pydantic Model（命名 `XxxPayload`），登记在发布方文档。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| EVENT_001 | 500 | 订阅了未登记的事件类型 | wiring 校验 fail-fast |

## 10. Cron / 任务

无（补偿 Cron 在具体落表组件内，如 mail）。

## 11. 测试边界

- publish 后 handler 异步执行（publish 返回时可能未完成）；`wait_idle()` 后可断言副作用。
- 一个 handler 抛异常：其余 handler 照常执行；错误日志含 event.type 与 handler 名；publish 不抛。
- 装配期结束后调用 subscribe → EVENT_001 类错误。
- 同一 event_type 多 handler 都被调用，顺序不保证（测试不得依赖顺序）。
- 事件类型未在文档登记 → wiring 完整性测试失败。

## 12. 未决事项

- 跨进程/可靠投递替换实现（Redis Stream / DB Outbox 投递器）：接口不变，ADR-0004 逃生门。

## 13. 实现边界（M1.7）

- `EventTypeRegistry` 和 `register_event_types` 是 wiring 的显式登记处；`EventBus` 默认引用进程 registry，确保后续 wiring 注册立即可见。
- `subscribe` 只在 `freeze()`/`seal()` 前允许调用；未登记类型或冻结后订阅统一抛 `EVENT_001`。
- `publish` 同步创建独立 asyncio Task，`wait_idle()` 等待当前及 handler 期间新增的任务；handler 异常在任务边界记录并隔离。
- `get_event_bus()` 提供生产单例，`fresh_event_bus(event_types)` 提供隔离测试实例；事件 payload 始终为 Pydantic Model。
