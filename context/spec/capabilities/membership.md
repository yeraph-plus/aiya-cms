# Membership Capability 规格

## 1. 职责

membership 管理会员等级（档位）、订阅周期、续费与到期，并维护会员开通时授予的积分额度。它是一级业务能力，不导入 points、payments、identity 或任何兄弟 capability。

- membership **不持有积分余额、不过期累进计算、不结算扣减**：授予额度经 `PointsLedger` Port 进入 points 的 expiring 桶（`expires_at = 订阅结束时刻`），到期后的剩余未消耗额度由 points 过期机制自动扣减，membership 只订阅、查看与续费。
- membership **不维护权益模型**：等级的价格、积分额度、续费周期由 membership 自身声明；注册奖励、赠送额度、邀请奖励等其他权益数值发生在业务流，由 feature 从 `site_settings` 读取后调用 points，不进入 membership。
- membership **不直接依赖用户系统**：subject 是 opaque reference，由组合根绑定的消费方 Port 校验存在性。
- 现金支付与 membership 无关：购买会员的支付流程由下游 feature（如 `membership_purchase`）组装 payments；membership 不导入 payments。

## 2. 表所有权

- `membership_levels`：level key、显示名、档位序号、状态、订阅周期（自然日）、每周期授予积分额度、续费允许开关、metadata。
  - 等级是代码/ops 声明（与 points behavior 一致），DB 行与声明对齐；运行期变更走受控 Command。
- `membership_subscriptions`：subject ref、level key、当前周期开始/结束时刻、状态、是否自动续费、授予积分额度快照、续费次数、取消/到期时间。
- `membership_renewal_records`（可选）：每次开通/续费的事实行：subscription、cycle start/end、granted points、调用 points 的 entry/source ref、结果状态。

subject 是 opaque reference，不建立 identity 外键。授予积分通过 Port 调用 points 公开 Command，不建 points 外键、不读 points 表。

### 2.1 Level 定义的导出边界

`membership level` 的定义管理是后端预留面：level key、周期、授予额度和策略继续由代码/ops 声明并与数据库行对齐。当前 `GET /api/v1/admin/membership/levels` 只导出已注册等级的只读目录；不导出创建、更新、删除或任意状态修改接口，管理员 SPA 不提供等级 CRUD 表单。

运行期若存在内部受控 level Command，它只供 install/ops 或明确 feature 使用，未进入 RouterSpec/OpenAPI。未来要开放任何等级管理动作，必须先明确版本、存量订阅快照、权限、审计和并发语义，再单独导出命名 Command，不能把 `membership_levels` 表直接映射为通用 CRUD。

`GET /api/v1/admin/membership/subscriptions` 支持 `subject_type`、`subject_id`、`level_key`、`status` 精确过滤，以便全局会员工作台和单用户 Drawer 复用同一个只读 Query；过滤不得隐式修改或续期订阅。

## 3. 状态机

订阅状态至少为：

```text
active ──到期──> expired
   │                │
   ├──取消──> cancelled（生效至周期结束）
   └──续费──> active（新周期）
```

- `active`：当前周期内，等级权益与授予额度有效。
- `expired`：周期结束且未续费；剩余未消耗的授予额度已由 points 过期机制扣减。
- `cancelled`：不再自动续费；当前周期继续有效到结束，结束时不自动进入新周期。

状态转换只由命名 Command 完成，不开放通用 status PATCH。

## 4. 授予与到期的积分语义

- 开通/续费时调用 `PointsLedger.grant_points`，credit 进入 points `expiring` 桶：
  - `expiration_identity = membership.grant`（behavior key，由 feature/组合根注册）。
  - `expires_at = 当前周期结束时刻`（与订阅 end 一致，精确到秒）。
  - 幂等键：`membership:grant:<subscription_id>:<cycle_end>`，重放不重复入账。
- **到期结算不另行实现**：points 过期任务在 `expires_at` 到达后自动清零剩余额度并记录 `expiration` ledger entry；membership 不累计"剩余未消耗"，不在到期时自行 DebitPoints。这保证"到期扣回剩余"与"过期先扣"共用同一机制，不会出现两套计算。
- 如果 points 侧 `expires_at` 入账失败（如临时错误），订阅开通必须整体失败回滚或通过 workflow 重试；不能出现"会员有效但额度未授予"。
- membership 只保存授予额度快照（便于展示与对账），不以此快照做扣减；快照与实际余额的差异由 points diagnostics 负责。

### 4.1 对 points 的契约依赖

membership 依赖 `CreditPoints` 支持**显式到期时刻**。points 已提供：`CreditDebitInput.expires_at` 可选字段，提供时优先于 behavior 的 `expiration_days` 计算桶的到期时刻，`expiration_identity` 仍为 behavior key：

- behavior 声明侧不变（`membership.grant` 为 credit 行为，`expiration_days` 可省略）。
- 桶的唯一键 `(account, expiration_identity, expires_at)` 不变；显式 `expires_at` 参与同一 `_credit_routing` 逻辑。
- `RebuildBalance` 的 credit 路由重放继续依赖 entry metadata 中的 `expires_at`（已存在），无需改动。

该扩展不改变 points 的桶模型、FIFO 扣减或过期任务语义，只放宽 credit 的到期来源。

## 5. Commands

- `SubscribeLevel`：为 subject 开通/变更到指定等级；校验 subject 存在（经 Port）、等级 active、当前订阅状态；创建/更新订阅并调用 grant_points 授予额度；幂等。
- `RenewSubscription`：续费当前订阅：推进周期 start/end、累加授予快照并再次 grant_points；要求订阅处于 active 且允许续费；幂等（重复续费请求返回原结果）。
- `CancelSubscription`：取消自动续费；当前周期继续有效。
- `TerminateSubscription`：管理员/系统显式终止（早退），立即结束周期并标记；不补偿已授予额度（由 points 过期机制按原 expires_at 处理）。
- 内部/后台 `ExpireSubscription`：cron 驱动的状态收敛（active 且 end <= now 且未续费 → expired）；不触碰 points（额度由 points 过期任务处理）。

## 6. 查询

- `ListLevels`：公开等级目录（含周期与授予额度）。
- `GetSubscription`：subject 当前订阅与周期、授予快照。
- `ListSubscriptions`：管理员分页。
- `GetRenewalRecords`：订阅的开通/续费事实。

查询不创建订阅；无订阅返回明确的 `no_subscription` 状态。

## 7. Port 与 adapter

membership 声明消费方 Port，由组合根绑定：

- `SubjectExistsPort`：`(subject_type, subject_id) -> bool`。组合根用 identity/feature 提供的 adapter 实现；未绑定则 Subscribe 类命令启动失败。
- `PointsLedgerPort`：
  - `grant_points(subject, amount, expires_at, idempotency_key, source_ref) -> entry_ref`
  - 组合根实现为调用 points 公开 `CreditPoints`（行为 `membership.grant`），只传数值与到期时刻，不读取 points 表。
  - 未来若需要"授予额度回收"语义，也经由 Port 暴露的 points 公开 Command（如 `DebitPoints`），membership 不做账本计算。

adapter 属于 `inc/adapters`（`adapters/membership/` 目录），遵循 `adapters.md` 目录合同；capability 不得反向导入 adapter。

## 8. 事件

- `membership.subscribed.v1`：subject、level、cycle start/end、granted points、subscription id。
- `membership.renewed.v1`：subscription、新周期 start/end、granted points。
- `membership.cancelled.v1`：subscription、当前周期 end（仍有效）。
- `membership.expired.v1`：subscription、周期 end、剩余额度信息不包含（余额以 points 账本为准）。

事件不包含 points 余额、payment 金额或订阅之外的跨能力快照。

## 9. 权限与审计

- `membership.manage`：管理员管理等级与终止订阅。
- 开通/续费/取消/终止全部审计。
- subject 的隐私字段不进入事件与日志。

## 10. 集成：购买会员（下游 feature 组装）

- `membership_purchase` feature 负责：受信价格目录（level key -> 金额/币种）→ payments 订单 → 捕获后调用 `SubscribeLevel` → 授予积分。
- 支付现金与积分互不参与：payments 只产生支付事实；membership 只在订阅成功事实后授予积分。
- 到期自动过期依赖 points 过期 Cron 与订阅 end 时刻一致；`ExpireSubscription` 由组合根注册为持久 `TaskInstance` handler，不允许只靠人工调用或内存 timer。

## 11. Diagnostics 与验收

- diagnostics 报告：`active` 但 end 已过期的订阅、有订阅但无授予积分记录（对账）、授予快照与 points 入账不一致、等级漂移（DB 与声明）。
- 重复订阅/续费请求只产生一次授予。
- 到期后剩余额度由 points 过期任务扣减，membership 不做第二套计算；测试验证"订阅结束前额度可消费、结束后剩余自动清零"。
- 订阅失败回滚时不得留下已授予但未开会员的积分。
- membership 在不导入 points/payments/identity 的情况下通过合同测试（Port 用 fake 实现）。
