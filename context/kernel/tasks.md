# Kernel / tasks（调度器壳 + BaseTask + Cron + LISTEN/NOTIFY）

## 1. 设计目的

统一异步任务设施（ADR-0005）：① APScheduler 壳——统一 API、幂等注册、隔离三方；② `BaseTask` 状态机——每个异步任务一个 class 闭环（错误处理/回滚/顺序保证）；③ Cron 注册表——服务器内部事务以系统 bot 运行并写审计；④ LISTEN/NOTIFY——仅任务即时唤醒（ADR-0011）。

非目标：不持久化作业定义（代码化注册）；不做多实例调度协调（本期单实例）。

## 2. 范围与依赖

- 代码位置: `inc/kernel/tasks/`
- 依赖的 kernel 组件: db, events, errors, logging, security（bot Principal）
- 被谁依赖: mail（重投）, auth（清理）, audit（清理）, modules（业务任务）
- 外部依赖: APScheduler 3.x, asyncpg（LISTEN）

## 3. 领域模型

- `TaskState(StrEnum)`：`pending → running → succeeded | failed | cancelled`。
- `BaseTask`（抽象基类，模板方法）：
  - 子类声明：`task_type: str`（唯一）、`Payload(BaseModel)`、`Result(BaseModel)`、`timeout_seconds: int`。
  - 子类实现：`async def run(self) -> Result`。
  - 可选钩子：`on_success(result)` / `on_failure(error)` / `rollback(error)`。
  - 壳行为（子类不可覆盖）：`execute()` = 创建 task_instances 行（pending）→ running → `asyncio.wait_for(run(), timeout)` → 成功：on_success → succeeded；异常：rollback → on_failure → failed（rollback 再抛错记 `rollback_error`）；超时：取消协程 → cancelled。每步状态翻转落库并发对应事件。
  - `await self.wait_wakeup(seconds)`：挂起等待唤醒信号（见第 5 节 LISTEN/NOTIFY）；超时返回 False。
- `TaskScheduler`（壳）：
  - `register_task_class(cls)`——登记 task_type（重复 → TASK_001 类校验）。
  - `start_task(task_type, payload, *, idempotency_key=None)`——幂等创建：同 idempotency_key 的未终结实例已存在则直接返回该实例（防重复创建）。
  - `register_cron(name, crontab, func)`——Cron 登记（重复名幂等跳过）；func 以系统 bot Principal 运行。
  - 启动时：代码化重建全部 Cron（MemoryJobStore 重启丢定义无影响）；扫描 stuck 实例（running 但进程已死）标记 failed（reason=orphan）。
- 事件：`task.started / task.succeeded / task.failed / task.cancelled`，payload `{task_id, task_type, ...}`。

## 4. 状态机

| 当前 | 事件 | 下一 | 备注 |
|---|---|---|---|
| pending | execute | running | |
| running | run 成功 | succeeded | on_success 后翻转 |
| running | run 异常 | failed | rollback→on_failure 后翻转 |
| running | 超时/主动取消 | cancelled | wait_for TimeoutError |
| running | 进程死亡（启动扫描） | failed | reason=orphan |

终态不可再转换（TASK_002）。

## 5. 数据库

### 表: `task_instances`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| task_type | str(64) | not null | 注册的类名 |
| state | str(16) | not null | TaskState |
| payload | jsonb | not null | → 子类 Payload Model（JsonBModel 动态绑定，注册时关联） |
| result | jsonb | null | → 子类 Result Model |
| error | jsonb | null | `TaskError{code,message,rollback_error?}` |
| idempotency_key | str(128) | null | 幂等键 |
| timeout_at | timestamptz | null | |
| started_at / finished_at | timestamptz | null | |
| created_at / updated_at | timestamptz | not null | |

索引: `ix_task_instances_type_state(task_type, state)`；`uq_task_instances_idem` partial unique(idempotency_key) WHERE 未终结。

JSONB Pydantic Model: `TaskError`（kernel）；Payload/Result 由各子类定义并在 `register_task_class` 时绑定。

### LISTEN/NOTIFY

- 通道唯一：`aiya_task_wakeup`；payload = task_instance UUID 字符串。
- 壳持有独立 asyncpg 连接 LISTEN；收到通知 → 查内存等待表 → 置对应 `asyncio.Event`。**唤醒是提示不是数据**：被唤醒方回表校验真实状态（ADR-0011）。
- 任何组件禁止新增其他通道/用途。

## 6. 公开 API

```python
class TaskState(StrEnum): ...
class BaseTask(ABC, Generic[TPayload, TResult]): ...
class TaskScheduler:
    def register_task_class(self, cls) -> None
    async def start_task(self, task_type: str, payload: BaseModel, *, idempotency_key: str | None = None) -> UUID
    def register_cron(self, name: str, crontab: str, func) -> None
    async def get_instance(self, task_id: UUID) -> TaskInstanceRead
```

### HTTP API（管理端）

| 方法 | 路径 | Capability | 响应 DTO | 说明 |
|---|---|---|---|---|
| GET | /api/v1/tasks | task:manage | Page[TaskInstanceRead] | 过滤 type/state |
| GET | /api/v1/tasks/{id} | task:manage | TaskInstanceRead | |

## 7. Pipeline

无。

## 8. Event

- 发布: `task.started` / `task.succeeded` / `task.failed` / `task.cancelled`。
- 订阅: 无。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| TASK_001 | 500 | 任务类型未登记/重复登记 | register/start_task |
| TASK_002 | 409 | 非法状态转换 | 终态再翻转 |
| TASK_003 | 504 | 任务超时 | wait_for 超时（实例置 cancelled） |
| TASK_004 | 404 | 任务实例不存在 | get_instance |

## 10. Cron / 任务

内核登记的 Cron（系统 bot）：

| 名称 | 表达式 | 动作 |
|---|---|---|
| tasks.reap_orphans | 每 10 分钟 | running 超时僵死实例 → failed(orphan) |
| auth.purge_expired_tokens | 每日 04:10 | 见 auth.md |
| mail.retry_failed | 每 5 分钟 | 见 mail.md |
| audit.purge_old_logs | 每日 04:30 | 见 audit.md |
| content.purge_trash | 每日 04:50 | 见 content.md；按 trashed_at 和 type retention 物理删除 |
| content.recount_comments | 每日 05:20 | 见 content.md；按冻结口径修复 comment_count |
| comment.purge_orphans | 每日 05:10 | 见 comment.md；清理目标不存在的占位评论 |

## 11. 测试边界

- 模板方法顺序：run 抛错 → rollback 被调用一次 → on_failure 被调用 → 状态 failed；rollback 也抛错 → error.rollback_error 有值。
- 超时任务 → cancelled，协程被真正取消（CancelledError 传播）。
- 幂等：同 idempotency_key 两次 start_task 返回同一 id，只建一行。
- Cron 重复注册同名 → 幂等跳过；Cron 函数收到的是系统 bot Principal。
- wait_wakeup：NOTIFY 到达立即返回 True（测试直接 pg_notify）；无通知超时返回 False，任务按自身超时逻辑终结。
- orphan 回收：手工插入 running 且 timeout_at 过期行 → reap_orphans 后变 failed。
- 终态实例再翻转 → TASK_002。

## 12. 未决事项

- 多实例部署：`pg_advisory_lock` leader 选举使 Cron 单实例运行（ADR-0005 逃生门）。
- 断线期间 NOTIFY 丢失的补扫（ADR-0011 逃生门：`wakeup_requested_at` 列）。

## 13. M1.10 实现状态

M1.10 已实现（2026-08-04）：`BaseTask`、`TaskScheduler`、`TaskUnitOfWork`、
`task_instances` 模型与 `0005_tasks` 迁移已落库。任务支持 pending/running/终态
流转、超时取消、rollback/on_failure 顺序、幂等启动、Cron 系统 bot、orphan
回收及 `task.*` 事件；LISTEN/NOTIFY 仅使用 `aiya_task_wakeup`，唤醒后回表校验。
对应 ADR-0024；管理端查询 API 仍由 M1.12 组合根提供。
