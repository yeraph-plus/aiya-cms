# Notification Capability 规格

## 职责与触发器

notification 负责通知 intent、模板、变量校验、投递状态和 provider 调用；feature/API 只提交公开 `RequestNotification`，不得自行渲染模板或实例化邮件 SDK。

本 release 内部注册且不可绕过的 trigger 白名单为：

- `identity.email_verification`
- `identity.password_reset`

每个 trigger 固定 channel、locale 策略和 Pydantic variables schema。公开调用使用 `trigger_name + recipient + variables + idempotency_key`；未知 trigger、未注册模板、缺失变量或多余变量全部拒绝。认证 challenge notifier 只能调用这两个 trigger。

## 模板

`notification_templates` 以 `(trigger_name, locale)` 绑定本地化内容，不能只以历史 template/spec key 派发。管理员可读写已注册 trigger 的模板，但更新必须验证 subject/body 占位符集合与该 trigger Pydantic schema 完全相同；不允许任意模板 key、未知 trigger 或自由变量。无法映射到白名单的旧模板不得继续派发，空库从受控导入重新建立。

intent 仅保存通过 schema 的 JSONB variables。挑战 token 和收件地址属于敏感数据：受保护保存，绝不进入 HTTP DTO、OpenAPI 示例、event、日志或 delivery attempt，且按 TTL/retention 清理。

## Port 与可靠投递

NotificationProvider 在每次投递使用 settings resolver 选择的 email adapter。adapter 不可用返回安全 `notification.provider_unavailable`；worker 将其作为可恢复的 provider unavailable 状态，不把 SDK/secret 原文保存进 attempt。intent 按业务幂等键去重，delivery 使用 lease，timeout/未知结果不得盲目重发。

管理员 router 只暴露命名的 delivery 查询、取消、重试及 trigger 约束的模板读取/更新；不提供泛化状态 PATCH 或绕过 trigger 的 CRUD。

## 验收

- 两个认证 trigger、严格 Pydantic variables、模板占位符、locale 查询和权限均有测试。
- 未知 trigger、未注册模板、变量缺失/多余、旧无 trigger 模板和 provider 缺配置均拒绝且不泄露敏感信息。
- 重复请求不新增 delivery；worker 崩溃、timeout 和 unavailable 的状态语义可恢复。
