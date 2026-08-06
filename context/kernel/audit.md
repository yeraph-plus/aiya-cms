# Kernel / audit

## 1. 设计目的

审计日志：谁在何时对什么做了什么。append-only 落库；写入走事件异步完成（不阻塞业务事务）；查询只读；定期清理由 Cron 以系统 bot 执行。

非目标：不做合规级防篡改（无签名链）；不做实时告警。

## 2. 范围与依赖

- 代码位置: `inc/kernel/audit/`
- 依赖的 kernel 组件: db, events, errors, logging, tasks
- 被谁依赖: 全部组件/模块（敏感操作登记审计）
- 外部依赖: 无新增

## 3. 领域模型

- `AuditService.record(action, actor, target=None, context=None, request=None)`：构造 `AuditRecorded` 内部事件并 publish（fire-and-forget）；监听器开 UoW 落 `audit_logs`。
- `action`：直接使用 Capability 别名或生命周期动作名（如 `user.login_failed`）——与权限点同一份登记处，天然对齐。
- `AuditContext(BaseModel)`（context JSONB 的 Model）：`reason: str | None`、`extra: dict[str, str] | None`（仅存字符串化的少量补充；结构化数据应进 target/action 设计而非堆 extra）。
- 触发纪律：rbac.md 第 6 节标记"审计: 是"的别名必须 record；生命周期事件（注册/登录失败等）由 auth/identity record。

## 4. 状态机

无（append-only）。

## 5. 数据库

### 表: `audit_logs`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| actor_id | uuid | null | null=匿名/系统 |
| actor_type | str(16) | not null | user/system_bot/anonymous |
| action | str(64) | not null | 别名或生命周期动作 |
| target_type | str(64) | null | 如 content/user |
| target_id | uuid | null | |
| context | jsonb | null | → AuditContext |
| ip | str(64) | null | |
| created_at | timestamptz | not null | 无 updated_at |

索引: `ix_audit_logs_action_time(action, created_at)`、`ix_audit_logs_actor_time(actor_id, created_at)`

JSONB Pydantic Model: `AuditContext`。

## 6. 公开 API

```python
class AuditService(Protocol):
    async def record(self, action: str, actor: Principal, *, target_type=None, target_id=None, context: AuditContext | None = None, ip: str | None = None) -> None
```

### HTTP API

| 方法 | 路径 | Capability | 响应 DTO | 说明 |
|---|---|---|---|---|
| GET | /api/v1/audit-logs | audit:read | Page[AuditLogRead] | 过滤 action/actor/时间窗 |

## 7. Pipeline

无。

## 8. Event

- 发布: 无（内部事件 `audit.recorded` 不外发）。
- 订阅: 内部监听器消费 record 请求落库（wiring 装配，kernel 内部自装配）。

## 9. 错误码

无独有（查询失败走 COMMON_*）。

## 10. Cron / 任务

| 名称 | 表达式 | 动作 |
|---|---|---|
| audit.purge_old_logs | 每日 04:30 | 物理删除 created_at < now-180d 的行；执行结果自身写一条审计 |

## 11. 测试边界

- record 后 `wait_idle` → 行落库，字段完整（actor/action/target/ip）。
- 业务事务失败回滚时审计仍应落库（record 在提交后调用，独立于业务事务）——对应测试：core 抛错时无审计行；提交成功后有。
- 敏感操作（如 user:ban）执行后必然产生对应 action 的审计行。
- purge Cron 删除超龄行且自身写审计。
- 表无 UPDATE 路径（无 updated_at 列，代码评审守护）。

## 12. 未决事项

- 保留期 180 天为初始值，运行后按量级调整（settings 化候选）。
