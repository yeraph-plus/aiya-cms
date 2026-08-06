# Kernel / mail

## 1. 设计目的

SMTP 封装 + "先落表后发送"的可靠语义（ADR-0004 的关键动作模式）：业务方 `enqueue` 即返回；发送失败由 Cron 重投兜底。dev 环境用 mailpit 捕获。

非目标：不做营销邮件批量发送；不做富模板引擎（简单 str.format 级模板，登记制）。

## 2. 范围与依赖

- 代码位置: `inc/kernel/mail/`
- 依赖的 kernel 组件: db, config, events, errors, logging, tasks
- 被谁依赖: auth（验证邮件，后期）, notification（后期模块）
- 外部依赖: aiosmtplib

## 3. 领域模型

- `MailTemplate` 登记：`name` + `subject_template` + `body_template` + `ContextModel(BaseModel)`。未登记模板不可用（MAIL_002）。
- 发送流程：`enqueue(to, template, context: BaseModel)` → 写 `mail_outbox`(pending) → 事务内 claim 为 `sending`（带租约）→ 立即尝试发送（进程内异步）→ 成功 sent / 失败 failed+last_error → `mail.retry_failed` Cron 重投（≤5 次，固定间隔+次数上限）→ 超限置 dead（人工干预）+ `mail.send_failed` 事件。租约防止多 worker 重复发送；过期租约可被 Cron 回收。

## 4. 状态机

| 当前 | 事件 | 下一 | 备注 |
|---|---|---|---|
| pending | 发送成功 | sent | |
| sending | 租约过期 | failed | Cron 回收并重试 |
| pending | 发送失败 | failed | attempts+1 |
| failed | Cron 重投成功 | sent | |
| failed | attempts≥5 | dead | 发 `mail.send_failed` |

## 5. 数据库

### 表: `mail_outbox`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| to_addr | str(320) | not null | |
| template | str(64) | not null | |
| context | jsonb | not null | → 各模板登记的 ContextModel |
| status | str(16) | not null | pending/sent/failed/dead |
| attempts | int | not null, default 0 | |
| last_error | str(1024) | null | |
| sent_at | timestamptz | null | |
| created_at / updated_at | timestamptz | not null | |

索引: `ix_mail_outbox_status(status, attempts)`

JSONB Pydantic Model: `context` 按 template 绑定登记的 ContextModel。

## 6. 公开 API

```python
class MailService(Protocol):
    async def enqueue(self, to: str, template: str, context: BaseModel) -> UUID
def register_mail_template(name: str, subject: str, body: str, ctx_model: type[BaseModel]) -> None
```

### HTTP API

无（管理端查看由 audit/日志承担，后期需要再加）。

## 7. Pipeline

无。

## 8. Event

- 发布: `mail.send_failed` `{mail_id, to, template, attempts}`（dead 时）。
- 订阅: 无。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| MAIL_001 | —（内部） | SMTP 发送失败 | 连接/认证/拒绝 |
| MAIL_002 | 500 | 模板未登记 | enqueue 未知 template |

## 10. Cron / 任务

| 名称 | 表达式 | 动作 |
|---|---|---|
| mail.retry_failed | 每 5 分钟 | failed 且 attempts<5 重投；超限置 dead 发事件 |

## 11. 测试边界

- enqueue 立即落表 pending（即使 SMTP 全挂，记录不丢）。
- 发送成功 → sent + sent_at；mailpit 可收（集成测试，dev 环境）。
- SMTP 失败 → failed + last_error；Cron 重投至 attempts=5 → dead + `mail.send_failed` 事件。
- 未登记模板 → MAIL_002。
- context 校验失败（与模板 ContextModel 不符）→ 拒绝 enqueue（COMMON_001）。

## 12. 未决事项

- HTML 邮件与多语言模板：后期随 notification 模块实装。
