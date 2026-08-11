# Audit Capability 规格

## 1. 职责

audit 持久化和查询跨能力产生的安全/管理审计事实。kernel 只提供 transport-neutral `AuditEnvelope` 和可靠 outbox 写入机制；具体审计记录、保留、权限和查询由本 capability 拥有。

audit 不代替领域事件、应用日志或 metrics，也不在 diagnostics 中自动生成/修复历史。

## 2. AuditEnvelope

业务 Command 在自己的 UoW 中把审计 envelope 与业务状态一同写入 kernel outbox。至少包含：

- 全局 record/event ID、occurred_at。
- owner、稳定 action key、outcome。
- actor subject/client/session opaque refs。
- target type/id。
- request/trace/correlation ID。
- source IP/user-agent 的受限摘要（确有安全需要时）。
- 受 Pydantic 模型约束的安全 metadata。

禁止记录 password、token、authorization code、client secret、支付签名、完整 webhook、完整通知正文或无关个人数据。

## 3. 表所有权

- `audit_entries`：不可变 envelope、ingested_at 和完整性版本。
- 可选 `audit_exports`：受控导出任务状态，不保存导出文件本体。

audit entry 创建后不得更新或删除；保留期清理由 `site_cleanup` feature 的明确运维
policy/activity 执行，并产生独立的 `audit.retention.cleaned` 审计摘要。策略值由
`site_settings.operations.audit_retention_days` 提供，且同时适用于 audit entry 和
kernel 的终态 outbox/inbox/task execution log。首版不实现篡改证明链，未来需要时新增
hash chain/外部归档规格。

## 4. 消费和失败语义

- producer 写审计 outbox 失败时，其敏感 Command 必须随 UoW rollback。
- audit inbox 以 envelope ID 去重，重复投递不重复记录。
- audit capability 暂时不可用不回滚已经提交的业务事实；outbox 持续重试并暴露积压告警。
- 无法解析的 schema version 进入隔离/告警，不能丢弃或猜测字段。

## 5. Queries 与权限

- `ListAuditEntries`：按 action、actor、target、outcome、时间范围分页。
- `GetAuditEntry`。
- 管理员可通过 execution entries read model 查看 outbox、inbox receipt 和 task 的安全摘要；该查询不返回 payload、result 或自由文本异常。
- `RequestAuditExport`：如首版启用，必须限范围、异步、可审计且输出到受控外部资产。

默认需要 `audit.read`；导出需要更高 `audit.export`。查询结果按最小披露返回，不允许任意 JSON path/SQL 过滤。

## 6. 初始必须审计的动作

- identity 封禁、删除、密码/邮箱安全变化。
- access 角色和权限变化、管理员 bootstrap。
- OIDC client/grant/session/revocation/key rotation 和 replay/reuse 安全事件。
- content 发布、归档和 purge。
- settings 修改。
- notification 人工 retry/cancel。
- points 管理员调整、冻结、reversal、余额修复。
- payments reconcile、capture/refund 管理操作。
- workflow 人工 retry/resume/cancel 和 diagnostics repair Commands。

## 7. Diagnostics 与验收

- diagnostics 检查 outbox audit backlog、隔离版本、保留任务失败和时间范围缺口，不修改记录。
- 同一 envelope 重放只产生一条 entry。
- 敏感 Command 的业务状态与审计 outbox 原子提交。
- 权限、分页和高基数筛选上限有测试。
- redaction 测试证明 secret/token/provider payload 不进入表、日志和 API。
- audit 不导入任何 producer capability。
