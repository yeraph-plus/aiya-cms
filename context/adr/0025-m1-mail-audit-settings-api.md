# ADR-0025: M1.11 内核落表组件与 M1.12 API 组合根实现

- 状态：accepted
- 日期：2026-08-04
- 关联：M1/A1 执行计划、ADR-0013、ADR-0014、ADR-0015、ADR-0016

## 决策

1. Mail 使用 `mail_outbox` 先落表后发送；SMTP 失败写入 `failed`，达到五次后转 `dead` 并发布 `mail.send_failed`。
2. Audit 使用进程内 `audit.recorded` 事件异步追加到 `audit_logs`；查询只读，清理由系统 bot Cron 执行。`audit_logs` 保持 append-only，不继承聚合表的 `updated_at` 约定。
3. Settings 使用显式 key/model/default 注册表，JSONB 值通过 Pydantic 模型边界，读取采用 cache-aside，更新删除缓存并发布 `setting.updated`。
4. API 组合根在 `inc/api/wiring.py` 显式装配错误码、Capability、Event、Cron 和全部 kernel Service；启动后冻结 EventBus，未登记项 fail-fast。
5. `/healthz` 仅提供进程存活；`/api/v1/health` 以只读探针返回 PostgreSQL/Redis 状态，依赖故障返回 `degraded` 而非抛出业务错误。
6. 浏览器 refresh token 按 ADR-0013 写入 httpOnly、SameSite=Strict、Path 限定 Cookie；非浏览器消费者仍可在请求体提供 refresh token。

## 验证

- Alembic `0006_mail_audit_settings` 建立三张 M1.11 表。
- 真实 PostgreSQL 认证链路覆盖注册、登录、me、refresh rotation、logout 和旧 token 重放保护。
- 后端 `ruff`、`mypy`、`pytest` 全绿，CodeGraph 在批量变更后同步。
