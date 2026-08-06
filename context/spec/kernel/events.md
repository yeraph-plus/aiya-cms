# Kernel Events 规格

## 1. 范围

kernel events 只实现可靠投递机制和信封，不定义任何业务事件。`ContentPublished`、`PaymentCaptured` 等 schema 由所属 capability 定义和版本化。

## 2. EventEnvelope

事件信封至少包含：

- `event_id`：全局唯一 UUIDv7。
- `event_key`：稳定点分 key，含 major schema version。
- `occurred_at`：事实发生的 UTC 时间。
- `producer`：owner capability/feature。
- `aggregate_type`、`aggregate_id`、可选 `aggregate_version`。
- `correlation_id`、`causation_id`、`trace_id`。
- `payload`：对应已注册 Pydantic schema。

信封不得携带 password、secret、完整 token、支付敏感数据或 provider 原始 webhook。

## 3. Outbox

- Command 在同一 UoW 内写业务状态和 outbox row。
- dispatcher 只领取已提交、到期且未完成的 row。
- 领取具备 lease，支持多 worker 和崩溃恢复。
- 投递语义为 at-least-once，不承诺 exactly-once 或跨 handler 顺序。
- retry 使用分类退避；超过上限进入 dead letter 并暴露诊断。
- 标记 delivered 不等于所有下游业务完成；每个 handler 独立记录结果。

## 4. Inbox 与 handler

- handler 以 `(handler_key, event_id)` 或更强业务幂等键去重。
- inbox receipt 和 handler 业务写入在同一 UoW 内提交。
- handler 不得直接写兄弟 capability 表；它只能属于目标 capability 并写自身表，或启动 feature workflow。
- 未知事件版本不得猜测解析，进入隔离状态并告警。
- 新增订阅只允许在 boot build phase，运行中 registry 已冻结。

## 5. 事件语义

- 事件名称使用过去式事实，例如 `content.published.v1`。
- 事件发生在业务状态提交语义上，不以“准备发布”冒充已发布。
- 业务流程需要返回值或立即失败时使用 Command/Port，不把事件总线当同步 RPC。
- 读请求不发业务事件；访问量等行为必须由显式写 Command/endpoint 产生。
- 不依赖不同 aggregate 事件的全局顺序。

## 6. Schema 演进

- 兼容新增可选字段可以保持 major version，消费者必须忽略允许的未知字段。
- 删除、改名、类型改变或语义改变必须发布新 event key/version。
- 旧 handler 退役前必须处理完对应 backlog 或显式迁移/隔离。
- 事件注册表在启动时验证 producer、schema、handler 支持版本。

## 7. 验收

- commit 失败时业务状态和 outbox 均不存在。
- commit 成功后进程立即崩溃，重启仍能投递。
- 重复投递不产生重复业务写入。
- handler 中途失败不会错误写入 inbox success。
- 未知版本、死信积压和 lease 超时进入 diagnostics/metrics。
