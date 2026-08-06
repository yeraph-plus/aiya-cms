# Kernel 技术内核规格索引

kernel 是冻结方向而非冻结实现：它只提供与具体业务无关的运行机制。任何包含 User、Role、OIDC、Content、Taxonomy、Notification、Points、Payment 等语义的模型或服务都不属于 kernel。

## 组件

- [`foundation.md`](foundation.md)：配置、错误、时间、ID、序列化和密码学原语。
- [`boot.md`](boot.md)：registry、声明加载、校验、freeze 和生命周期接口。
- [`database.md`](database.md)：Base、Repository/UoW、JSONB、事务和迁移。
- [`events.md`](events.md)：durable outbox/inbox 和事件投递。
- [`workflow-tasks.md`](workflow-tasks.md)：持久化 workflow、activity、task、Cron 和 worker。
- [`observability.md`](observability.md)：日志、metrics、diagnostics、readmodel 和健康检查合同。

## Kernel 公开面

kernel 可以公开：

- 基础 DTO/Protocol 和不可变声明类型。
- `Base`、字段 mixin、Repository/UoW 抽象和工厂。
- EventEnvelope、OutboxWriter、InboxGuard、dispatcher contracts。
- WorkflowSpec、ActivitySpec、Signal、RetryPolicy、TaskScheduler contracts。
- Registry/Manifest 校验原语。
- Clock、ID generator、Hasher/Signer/KeyLoader 等无业务含义接口。
- 结构化错误、日志字段、metrics/diagnostics provider contracts。

kernel 不公开“继承后自动工作”的业务基类。创建对象、注册声明、打开连接和启动 worker 均由组合根完成。

## Kernel 表所有权

kernel 只拥有技术表：

- outbox messages。
- inbox receipts/handler deduplication。
- workflow instances、steps/signals。
- task instances、leases、dead letters。

业务审计、业务设置、用户会话、通知投递、积分流水等表分别归属 capability。通用技术表不得增加只服务某一 capability 的业务列；扩展信息使用有 schema 的 metadata 或由所属 capability 建表。

## 变更规则

- kernel 公共面变更必须先更新本目录规格和架构合同测试。
- 新机制必须有至少两个真实消费者，或是 outbox/workflow 等已确认的基础可靠性要求。
- 破坏性 DTO/持久状态变化必须带版本和迁移策略。
- kernel 单元测试不得依赖具体 capability fixture。
- capability 测试可以用 kernel 的 in-memory/test adapter，但生产语义必须在 PostgreSQL/Redis 环境复验。

## 验收

- kernel 可在空 manifest 下独立导入和启动。
- import 不产生线程、连接、注册或数据库写入。
- kernel 测试源码不需要导入业务模型。
- kernel 表之外的 metadata owner 清单为空。
- 上层不存在通过继承私有 kernel 类绕过公开合同的实现。
