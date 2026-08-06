# Kernel Workflow、Task 与 Cron 规格

## 1. 概念边界

- **workflow**：持久化的多步骤业务编排，可等待 signal、重试和恢复。
- **activity**：workflow 调用的单个可执行步骤，可以访问一个 capability 或一个外部 adapter。
- **task**：activity/Cron handler 的持久执行实例。
- **Cron**：只产生到期触发，不承载长期业务状态。

kernel 实现运行时，具体 workflow/activity/Cron 由 capability 或 feature 注册。

## 2. 持久状态

workflow instance 至少记录：

- workflow key/version、instance ID、business idempotency key。
- 输入和当前 state 的 Pydantic schema version。
- pending/completed/failed/cancelled/waiting 状态。
- 当前步骤、attempt、wake time、correlation/trace ID。
- 接收过的 signal 和最终 result/error summary。

task/activity 记录 lease owner/expiry、attempt、timeout、next run、result/error category。payload 不得包含 secret。

## 3. 执行语义

- workflow 每推进一步都提交持久状态，不持有跨步骤数据库事务。
- activity 默认 at-least-once，注册时必须声明幂等策略。
- 外部调用必须设置 connect/read/overall timeout。
- retry policy 区分 transient、rate limit、conflict、permanent 和 cancelled。
- retry 有最大次数/持续时间并加入 jitter；禁止无限热循环。
- worker 失联后 lease 到期可重新领取，同一业务结果仍由幂等约束保护。
- shutdown 只停止领取新任务，在 grace period 内完成或安全释放当前任务。

## 4. Signal 与等待

- signal 使用 `(workflow_id, signal_key, signal_id)` 唯一去重。
- signal 可在 workflow 进入 waiting 前到达，运行时必须持久保存后消费。
- 未注册 signal、错误 payload version 或已终结 workflow 的 signal 返回稳定结果。
- 等待不占用线程、连接或数据库事务。

## 5. 补偿与人工恢复

- compensation 是显式 activity，不自动反转数据库或外部世界。
- 已发送通知、已公开内容、已捕获支付等不可逆事实必须保留并通过后续动作处理。
- dead workflow 保留失败步骤和上下文，管理员可执行 retry/resume/cancel 等有权限且审计的 Command。
- diagnostics 只报告，不自动 retry 或修改状态。

## 6. Cron

- CronSpec 包含稳定 key、schedule/timezone、misfire policy、并发策略和 handler activity。
- schedule 使用显式业务时区；持久执行时间仍保存 UTC。
- 多实例环境只允许 lease holder 产生同一触发；handler 仍需幂等。
- 定时发布等任务重启后必须通过数据库重新扫描到期项，不能依赖内存 timer。

## 7. 版本演进

- 持久化 workflow 的破坏性流程/state 变化必须新增 workflow version。
- 旧版本实例必须继续由旧 runner 完成，或提供显式 state migration。
- activity key 语义不可原地替换；输入输出破坏性改变时新增版本。

## 8. 验收

- 在每个 commit 前后注入崩溃，workflow 最终状态正确且副作用不重复。
- signal 提前、重复、乱序到达均有确定行为。
- lease 竞争、超时、shutdown、dead letter 和人工恢复测试通过。
- 重放不直接读取当前时间、随机数或网络。
- 未注册 workflow/activity/Cron 阻止启动。
