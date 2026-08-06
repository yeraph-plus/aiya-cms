# Kernel 可观测性与诊断规格

## 1. 结构化日志

- 日志至少关联 request/trace/correlation ID、owner、operation 和 duration。
- workflow/activity 日志包含 instance、step、attempt；不得记录完整 payload。
- 默认 redaction authorization、cookie、password、client secret、token、支付签名和 provider credential。
- 用户可见错误与内部异常分离；堆栈只进入受控日志。
- 日志失败不得改变业务事务结果。

## 2. Metrics

kernel 定义 counter/gauge/histogram provider contract 和统一命名约束。capability 自己声明业务指标。

至少包含：

- HTTP request count/latency/error。
- DB pool/transaction failure。
- outbox pending age、delivery/retry/dead count。
- workflow/activity state、duration、retry/dead count。
- task lease/queue lag。

label 必须低基数；禁止使用 user ID、content ID、token、URL 全路径或异常 message 作为 label。

## 3. Diagnostics

- `diagnostics.py` 提供只读一致性和依赖检查。
- diagnostics 不修复、不 enqueue event、不触发重试、不刷新状态。
- 每项结果区分 `ok`、`degraded`、`failed`、`unavailable`，并包含稳定 code 和安全摘要。
- 深度扫描必须显式触发、分页/限时，不放入普通 readiness。
- 修复操作是单独 Command，要求 access capability、审计和可选 dry-run。

## 4. Admin readmodel

- capability 可以注册 `AdminSummaryProvider`，返回自己的聚合 DTO。
- API 只汇总已启用且当前 Principal 有权读取的 provider。
- 状态必须区分未启用、无权限、查询失败和真实零值，不用 `null` 混淆。
- readmodel 可以缓存或使用投影表，但不能由 GET 临时写业务表。
- 删除旧 dashboard 直接注入多个 Service 并查询其表的实现。

## 5. 健康检查

- `/healthz` 只表示进程存活，不访问外部依赖。
- `/api/v1/health` 表示 readiness，检查数据库和当前 manifest 必需依赖，必须有严格超时。
- 可选 provider 故障按 manifest 策略表现为 degraded 或 failed。
- 深度业务 diagnostics 不进入编排器高频 health probe。

## 6. 审计边界

kernel 提供技术 AuditEnvelope/Writer Port；业务审计事件和保留策略由 capability/feature 定义。审计写入失败对敏感 Command 的 fail-open/fail-closed 策略必须由该 Command 规格明确。

审计记录不得保存 secret、完整 token、支付敏感 payload 或不必要的个人数据。

## 7. 验收

- diagnostics 执行前后业务表、outbox 和 task 数量不变。
- metrics label cardinality 有合同测试。
- secret redaction 覆盖 HTTP、workflow 和 provider error。
- readiness 具备超时且不执行深扫描。
- readmodel provider 的权限、失败和未启用状态可区分。
