# Points Capability 规格

## 1. 职责

points 管理积分计划、主体账户、不可变账本、余额快照、积分桶（bucket）和由 feature 注册的行为规则。它是一级业务能力，但不属于 kernel。

points 不知道发帖、签到、商品或支付 SDK；这些语义通过 behavior code、source reference 和 feature workflow 接入。

首版默认可用积分计划 key 为 `credit`。`points_programs` 的其他策略字段保留为模型预留，本轮不扩展其业务语义。

积分是系统内唯一资源货币。下游业务链只向 points 声明“需要增减多少积分”（以 behavior 注册），不自行计算过期或剩余扣除；过期一律由 points 的桶过期机制处理。

## 2. 表所有权

- `points_programs`：program key、显示名、单位、状态、是否允许管理员冲正等策略。
- `points_accounts`：program_id、subject_type、subject_id、state、version、created/updated。
- `points_balances`：account_id、balance、version、updated_at；是同事务快照，表示账户可用余额。
- `points_buckets`：消费与过期层数据结构，记录账户下积分存放与到期情况：
  - `perpetual` 桶：无到期日，每账户最多 1 个，承载永久积分。
  - `expiring` 桶：有到期日，按 `(expiration_identity, expires_at)` 唯一，承载有期积分。
  - amount 为桶内当前可用数量（>= 0）；version 乐观锁。
- `points_debit_allocations`：记录 Debit/过期/冲销实际消费（或归还）的桶，每条 `(entry, bucket)` 唯一，amount 为绝对值。
- `points_ledger_entries`：account、signed amount、entry type、behavior key/version、source type/id、idempotency key、actor ref、metadata、reversal_of、created_at。entry type 含 `credit|debit|adjustment|reversal|expiration`。
- `points_behavior_definitions`：已部署 behavior 的 key/version/非执行元数据，用 migration/ops 与代码 registry 对齐。

subject/source/actor 是 opaque reference，不建立 identity/content/payment 外键。账本是事实来源，balance 可以从账本重算。

### 2.1 Program 定义的导出边界

`points program` 由管理员受控维护：key 不可变，支持创建、描述/单位/冲正策略编辑、启用/停用、汇总和账户列表；存在账户后单位不可变，默认 `credit` 计划不可停用。所有变更要求 `points.programs.manage`、版本并发检查和审计，停用不删除历史账本。

管理员 HTTP 面导出受控的 program catalog：`GET/POST /api/v1/admin/points/programs`、`PATCH /api/v1/admin/points/programs/{program_key}`、`POST .../activate|deactivate`、`GET .../summary` 和 `GET /api/v1/admin/points/accounts`。program key 不可变；存在账户后单位不可变；默认 `credit` 计划不可停用；停用时若仍有已注册行为或非零余额必须拒绝。所有写入带 `expected_version`、reason（状态/冻结）和审计事件，未知 key 必须由后端拒绝。

## 3. 不变量与执行模型

### 3.1 执行模型：时序单步 + 幂等 + 账本级乐观锁

points 按“时序单步”设计，不引入行锁、分布式锁或并发重试框架：

- 部署约束：生产为**单 API + 单 worker 实例**（`context/spec/composition.md` 部署章节），水平扩容只扩无状态层；多实例部署下本模型不成立。
- 同一账户的积分修改频率低（签到、下载、AI 调用均为低频用户动作），同账户并发只可能来自用户连点或 cron 与请求竞争。
- 唯一必须的并发保护是**账本级乐观锁**：`points_balances.version` 条件更新（`UPDATE ... WHERE account_id=? AND version=?`），rowcount=0 视为冲突报错，由调用方（workflow）重试。桶的条件更新同理（`WHERE id=? AND version=?`）。
- 不依赖数据库行锁（`FOR UPDATE`）、应用锁或进程内互斥。读取-计算-写入在同一 UoW 内串行执行，冲突由版本条件更新在提交前拦截。
- 所有跨命令/跨请求的时序由以下机制承担，points 不再自建：
  - 幂等键：同一 `(program_id, idempotency_key)` 最多一条流水，重放返回原结果。
  - workflow 单步：feature 通过 workflow activity 调用 points command，每个 activity 独立提交、可重试。
  - 后台任务单实例：过期扫描、会员结算等后台任务在单 worker 进程内以持久 task 顺序执行（由组合根注册的 CronSpec 驱动），同一时刻仅一个执行者。

### 3.2 不变量

- amount 是非零整数；禁止浮点数。
- 普通 debit 后 balance 不得小于 0。
- 同一 `(program_id, idempotency_key)` 最多一条原始业务流水。
- ledger entry 创建后不可更新或删除；纠错通过新 reversal/adjustment entry。
- 每条 entry 的 balance 变化和 balance snapshot 在同一 UoW 提交。
- reversal 对同一原 entry 最多成功一次，并建立 `reversal_of` 关系。
- **每笔 credit 产生独立 ledger entry；credit 的资金按 expiration identity 进入积分桶**：
  - behavior 无 `expiration_days` 且调用未提供显式 `expires_at` → 进入账户级 `perpetual` 桶（每账户最多 1 个）。
  - behavior 有 `expiration_days`（或调用显式提供 `expires_at`）→ 进入 `expiring` 桶，`expiration_identity = behavior key`，`expires_at = 显式值或 created_at + expiration_days`。显式 `expires_at` 优先（如 membership 以订阅结束时刻为到期）。
- 桶不是与 credit 一一对应的结构，同一 `(account, expiration_identity, expires_at)` 的 credit 共享一个桶。
- **debit 按过期先扣（FIFO by expires_at）**：按 `expires_at ASC NULLS LAST, created_at ASC` 遍历桶扣减；每次扣减为 `points_debit_allocations` 记录实际消费的桶和数量。
- **过期**：桶到达 `expires_at` 后，剩余额度由 points 过期任务产生 `entry_type="expiration"` 的 ledger entry 并从桶中清零，同时记录 allocation。
- `balance == SUM(points_buckets.amount)` 在正常状态恒成立；debt 状态下 balance 可以为负、桶之和为 0（扣减已无桶可扣的差额进入 debt）。
- 系统性 reversal（例如已退款但积分已消费）允许使 balance 变为负数；账户进入 debt 状态，禁止继续普通 debit，后续 credit 先抵消负值。该事实不得因余额不足而丢失。

## 4. PointBehaviorSpec

feature 注册：

- 稳定 behavior key/version。
- program key 和方向 `credit|debit`。
- 固定值或受约束的 amount policy。
- 单次上下限、冷却、每日/周期次数。
- `expiration_days`：credit 方向下积分有效期（自然日）；`None` 表示永久积分（进入 perpetual 桶）。debit 方向不适用。
- 业务时区和活动有效窗口。
- metadata Pydantic schema。
- 允许的 source/actor types 和所需 access capability。

行为是代码声明，不把表达式或脚本存入数据库。points 执行通用约束，feature 决定何时调用。

初始行为至少包括：

- `daily_check_in.reward`（credit，可配置过期）
- `purchase.completed.credit`（credit，可配置过期）

`post.published.reward` 只是可选示例，未被 feature/manifest 注册时不生效。

## 5. Commands

- `OpenPointsAccount`：开户时同时创建零余额 perpetual 桶。
- `CreditPoints`：幂等入账；创建 ledger entry 后按 behavior 路由到 perpetual 或 expiring 桶，同事务更新余额快照。`CreditDebitInput` 可携带显式 `expires_at`（优先于 behavior 的 `expiration_days`）。
- `DebitPoints`：按 `expires_at ASC NULLS LAST` 顺序消费桶（过期先扣），跨桶扣减，逐桶记录 allocation；不足则拒绝并不得部分扣减。
- `ReverseLedgerEntry`：
  - 反转 debit/expiration 类 entry：按其 allocations 原路归还对应桶。
  - 反转 credit 类 entry：按 debit 语义从桶中扣回（可进入 debt），记录 allocation。
- `ExpireBuckets`：扫描 `expires_at <= now` 且 `amount > 0` 的 expiring 桶，为剩余额度生成 `expiration` ledger entry、清零桶、记录 allocation；可重复执行（幂等）。由组合根注册的 `points.buckets.expire.v1` Cron task 驱动；与 debit 竞争由 version 条件更新和幂等键拦截，不使用行锁。
- `AdjustPoints`：仅管理员，要求 reason、权限和审计；正向调整入 perpetual 桶，负向调整按 debit 语义扣桶。`program_key` 可省略，省略时使用默认 `credit` 计划。HTTP 面由 admin router 暴露（`POST /api/v1/admin/points/adjust`，`points.adjust` 权限，带 `idempotency_key`）。
- `FreezePointsAccount` / `UnfreezePointsAccount`
- 运维 `RebuildBalance`：dry-run 比较后显式修复，不能由 Query 自动执行；从 ledger 重算余额，并按 credit 路由信息与 allocations 重建桶。

Credit/Debit 必须校验 behavior、subject/source、周期限制、账户状态和幂等键。首次 Credit/Debit/Adjust 写入若账户不存在，在同一 UoW 内隐式创建默认计划对应的主体账户、余额快照和 perpetual 桶；开户事实与业务流水一起提交。扣减唯一依赖**version 条件更新**（balance 行与受影响桶行）保证并发不超扣；不使用行锁或进程锁。

## 6. Queries

- `GetBalance`：返回可用余额及桶明细（perpetual 余额、expiring 桶列表）。
- `ListLedger`：账本分页，包含每条 entry 的 bucket allocations。
- `GetLedgerEntry`
- `ListBuckets`：账户下所有桶状态（identity、expires_at、amount），供管理员/诊断查看。
- `GetBehaviorCatalog`

Query 不创建账户；不存在账户时可以返回明确 `not_opened` 或逻辑零值 DTO，但不得隐式写库。公开余额和后台账本权限分离。

HTTP 自助面由组合根提供 `GET /api/v1/me/points/ledger`，只允许当前 subject 读取默认 `credit` program 的分页账本；管理员面提供 `GET /api/v1/admin/points/ledger`，要求 `points.read`，可按主体读取默认 `credit` 或指定 program 的余额、桶及分页账本。两个 GET 都不得创建账户或产生其他副作用。

## 7. 事件

- `points.account_opened.v1`
- `points.credited.v1`
- `points.debited.v1`
- `points.entry_reversed.v1`
- `points.bucket_expired.v1`
- `points.account_frozen.v1`

事件包含 program/account/entry、amount、behavior/source ref 和 resulting balance，不包含跨能力业务快照。

## 8. 签到与购买接入

- `user_center` 的 check-in 流程使用 `subject + program + business_date` 形成幂等键并调用 `CreditPoints`。
- `user_center` 的 point purchase workflow 只在受信 `payment.captured.v1` 事实后调用 `CreditPoints`。
- 支付退款调用 `ReverseLedgerEntry`，重复退款事件返回原 reversal。
- points 不订阅所有 content/payment 事件后自动猜测奖励。

## 9. Diagnostics、审计与验收

- diagnostics 比较 ledger sum 与 balance、`balance` 与 `SUM(buckets.amount)`、检查重复 source/idempotency、非法负余额状态、孤儿 subject/source、过期未清桶和 behavior definition 漂移。
- 管理员调整、冻结、重建余额和 reversal 全部审计。
- 并发 debit 总额不能超过余额；不使用行锁/进程锁，仅靠 version 条件更新，测试在串行执行下仍正确。
- 同一幂等键并发 credit 只产生一条流水。
- ledger 可完整重算 balance，entry 不可更新/删除。
- reversal 即使造成负余额也保留会计事实并限制后续 debit。
- debit 始终先扣最早过期的桶；过期任务与 debit 竞争时靠 version 条件更新拦截，不重复扣减。
- points 在不导入 identity/content/payments 的情况下通过合同测试。
