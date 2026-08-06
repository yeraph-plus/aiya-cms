# ADR-0005: 任务调度器壳 + BaseTask 抽象基类（APScheduler 3.x）

- 状态: accepted
- 日期: 2026-08-02
- 决策者: 项目所有者 + AI 协作
- 关联: [kernel/tasks.md](../kernel/tasks.md)

## 背景

系统需要：① 轻量状态机（异步任务的编排、超时取消、回滚、顺序保证）；② 独立 Cron Job（审计清理、日志清理、邮件重投等服务器内部事务）；③ 统一 API 简化下游使用，并在一处处理重复创建等问题。所有者要求"不造轮子"，基于 APScheduler 之类的现成框架做壳，工厂式地让每个异步任务在一个 class 内闭环。

## 决策

1. **kernel 提供调度器壳 `TaskScheduler`**：封装 APScheduler 3.x `AsyncIOScheduler` + MemoryJobStore；统一注册/取消/幂等（同名任务重复注册直接返回已有，不报错不重复）。
2. **`BaseTask` 抽象基类（模板方法）**：子类实现 `run()`；壳提供 `on_success()` / `on_failure()` / `rollback()` 钩子；`run()` 外包 try 结构保证失败回滚；内置状态机（StrEnum：`pending → running → succeeded / failed / cancelled`），超时自动取消，结束自动关闭；状态持久化 `task_instances` 表。
3. **Cron 注册表**：`TaskScheduler.register_cron(name, trigger, func, ...)` 显式登记；Cron 任务以**系统 bot 主体**运行，行为写审计日志。
4. 任务代码化注册：所有任务/Cron 在代码中定义，应用启动时幂等重建（MemoryJobStore 重启丢任务不构成问题，因为注册即代码）。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| APScheduler 4.x | async 原生重构 | API 大改、生态与文档成熟度不及 3.x | 壳隔离后 3.x 稳定够用；替换成本低 |
| APScheduler SQLAlchemyJobStore 持久化作业 | 重启不丢作业定义 | 3.x jobstore 走同步驱动，与全异步栈冲突；作业定义代码化后无必要 | 状态持久化已有 task_instances，作业定义本就在代码里 |
| Celery / Dramatiq 等任务队列 | 功能全 | 需要 broker，所有者明确不引入 MQ | 明确被否 |
| 装饰器形态（@task）为主 | 轻便 | 复杂任务的状态/回滚逻辑分散，不利于"一个 class 闭环调试" | 基类形态与所有者设计一致 |

## 后果

### 正面
- 下游只需继承 BaseTask 一个 class 即获得状态机、回滚、超时、持久化；调试时单点入口。
- APScheduler 被壳隔离，未来换 4.x 或其他调度器不影响任务子类。

### 负面 / 代价
- MemoryJobStore 意味着定时触发历史不可追溯（状态历史在 task_instances，接受）。
- 单实例假设：多实例部署时 Cron 会在每个实例重复触发（本期单实例；后期需在壳内加 PG  advisory lock 选举）。

### 逃生门
- 壳内换调度器实现（4.x / 自研 DB 轮询）对任务子类透明。
- 多实例需求出现时，在壳内加 `pg_advisory_lock`  leader 选举，不动任务定义。
