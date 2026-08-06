# Points Capability 规格

## 1. 职责

points 管理积分计划、主体账户、不可变账本、余额快照和由 feature 注册的行为规则。它是一级业务能力，但不属于 kernel。

points 不知道发帖、签到、商品或支付 SDK；这些语义通过 behavior code、source reference 和 feature workflow 接入。

## 2. 表所有权

- `points_programs`：program key、显示名、单位、状态、是否允许管理员冲正等策略。
- `points_accounts`：program_id、subject_type、subject_id、state、version、created/updated。
- `points_balances`：account_id、balance、version、updated_at；是同事务快照。
- `points_ledger_entries`：account、signed amount、entry type、behavior key/version、source type/id、idempotency key、actor ref、metadata、reversal_of、created_at。
- `points_behavior_definitions`：已部署 behavior 的 key/version/非执行元数据，用 migration/ops 与代码 registry 对齐。

subject/source/actor 是 opaque reference，不建立 identity/content/payment 外键。账本是事实来源，balance 可以从账本重算。

## 3. 不变量

- amount 是非零整数；禁止浮点数。
- 普通 debit 后 balance 不得小于 0。
- 同一 `(program_id, idempotency_key)` 最多一条原始业务流水。
- ledger entry 创建后不可更新或删除；纠错通过新 reversal/adjustment entry。
- 每条 entry 的 balance 变化和 balance snapshot 在同一 UoW 提交。
- reversal 对同一原 entry 最多成功一次，并建立 `reversal_of` 关系。
- 首版积分不自动过期，不实现 FIFO lot/expiration。

系统性 reversal（例如已退款但积分已消费）允许使 balance 变为负数；账户进入 debt 状态，禁止继续普通 debit，后续 credit 先抵消负值。该事实不得因余额不足而丢失。

## 4. PointBehaviorSpec

feature 注册：

- 稳定 behavior key/version。
- program key 和方向 `credit|debit`。
- 固定值或受约束的 amount policy。
- 单次上下限、冷却、每日/周期次数。
- 业务时区和活动有效窗口。
- metadata Pydantic schema。
- 允许的 source/actor types 和所需 access capability。

行为是代码声明，不把表达式或脚本存入数据库。points 执行通用约束，feature 决定何时调用。

初始行为至少包括：

- `daily_check_in.reward`
- `purchase.completed.credit`

`post.published.reward` 只是可选示例，未被 feature/manifest 注册时不生效。

## 5. Commands

- `OpenPointsAccount`
- `CreditPoints`
- `DebitPoints`
- `ReverseLedgerEntry`
- `AdjustPoints`：仅管理员，要求 reason、权限和审计。
- `FreezePointsAccount` / `UnfreezePointsAccount`
- 运维 `RebuildBalance`：dry-run 比较后显式修复，不能由 Query 自动执行。

Credit/Debit 必须校验 behavior、subject/source、周期限制、账户状态和幂等键。扣减通过条件更新或账户行锁保证并发不超扣。

## 6. Queries

- `GetBalance`
- `ListLedger`
- `GetLedgerEntry`
- `GetBehaviorCatalog`

Query 不创建账户；不存在账户时可以返回明确 `not_opened` 或逻辑零值 DTO，但不得隐式写库。公开余额和后台账本权限分离。

## 7. 事件

- `points.account_opened.v1`
- `points.credited.v1`
- `points.debited.v1`
- `points.entry_reversed.v1`
- `points.account_frozen.v1`

事件包含 program/account/entry、amount、behavior/source ref 和 resulting balance，不包含跨能力业务快照。

## 8. 签到与购买接入

- check-in feature 使用 `subject + program + business_date` 形成幂等键并调用 `CreditPoints`。
- point_purchase workflow 只在受信 `payment.captured.v1` 事实后调用 `CreditPoints`。
- 支付退款调用 `ReverseLedgerEntry`，重复退款事件返回原 reversal。
- points 不订阅所有 content/payment 事件后自动猜测奖励。

## 9. Diagnostics、审计与验收

- diagnostics 比较 ledger sum 与 balance、检查重复 source/idempotency、非法负余额状态、孤儿 subject/source 和 behavior definition 漂移。
- 管理员调整、冻结、重建余额和 reversal 全部审计。
- 并发 debit 总额不能超过余额；进程锁关闭后测试仍正确。
- 同一幂等键并发 credit 只产生一条流水。
- ledger 可完整重算 balance，entry 不可更新/删除。
- reversal 即使造成负余额也保留会计事实并限制后续 debit。
- points 在不导入 identity/content/payments 的情况下通过合同测试。
