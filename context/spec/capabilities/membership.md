# Membership Capability 规格

> 状态：目标边界。跨能力装配由 [`user_center`](../features/user-center.md) 完成；开发阶段 baseline 直接按当前 metadata 重建。

## 1. 职责

membership 只管理会员等级、订阅、周期和状态转换。它拥有会员领域的规则与原子操作，不导入 points、payments、gift_cards、identity 或任何兄弟 capability。

- 等级定义周期长度、周期赠送积分额度、是否允许续费等会员规则。
- 订阅保存当前等级、周期边界、状态和购买来源的 opaque ref。
- membership 不持有积分余额、不创建 points 流水，也不回收或过期积分。
- membership 不处理现实法币订单、支付 attempt、webhook 或退款。
- subject 是 opaque reference；存在性与当前操作者权限由调用方和组合根校验。

会员周期赠送积分是“会员周期事实 + points 显式到期 credit”的跨能力业务流，必须由 `user_center` 编排，不能在 membership 内伪装成 Port 调用。

## 2. 表所有权

- `membership_levels`
  - `key`、显示名、档位顺序、状态；
  - `cycle_days`；
  - `cycle_points_amount`；
  - `renewal_allowed`；
  - `version`、metadata、审计时间。
- `membership_subscriptions`
  - subject ref、level key；
  - 当前周期 start/end；
  - `status`、是否自动续费；
  - 等级与额度快照；
  - 当前 `cycle_id`、购买/兑换来源 opaque ref；
  - 版本、取消/到期/终止时间。
- `membership_cycles`
  - subscription、cycle start/end、level/额度快照；
  - `state`；
  - `source_type`、`source_ref`；
  - `points_entry_ref`；
  - 幂等键、失败原因码和审计时间。

不建立 identity、payments、gift_cards 或 points 外键。`points_entry_ref` 只保存 points 返回的 opaque UUID 字符串，不作为跨库联表依据。

开发阶段不兼容旧 subscription/renewal 数据：`release_0001` 直接创建上述当前结构，不创建 `membership_renewal_records`，也不包含 `ALTER`、旧状态转换或数据搬迁。

## 3. 等级生命周期

level key 创建后不可变。创建、编辑、启用、归档均为命名 Command，并要求：

- `membership.levels.manage`；
- 乐观并发版本；
- 审计；
- 对存量订阅保留快照。

归档阻止新开通和续费，不改变已经激活的周期。管理员 HTTP 可以是所属 capability 的普通管理面适配，不需要额外 feature 包装。

## 4. 周期状态机

订阅状态：

```text
pending_activation ──周期积分已入账──> active ──到期──> expired
        │                                │
        └────────失败/放弃──────────────> failed
                                         ├─取消自动续费──> cancelled
                                         └─立即终止──────> terminated
```

周期事实状态：

```text
prepared ──AttachPointsGrant──> activated
    │
    └─MarkCycleFailed────────> failed
```

- `prepared` 周期不授予会员权益；只表示 membership 已验证等级并保留确定的 start/end/额度快照。
- `activated` 必须带有效 `points_entry_ref`；membership 才把订阅切换为 `active`。
- `cancelled` 表示停止自动续费，当前已激活周期仍持续到 end。
- `terminated` 是显式提前终止；默认不补偿已经发放的积分。若未来需要补偿，仍由 feature 调用 points 的公开 Command。
- `expired` 只收敛会员状态；points 自己负责到期桶的清零事实。

状态不得通过通用 status PATCH 修改。

## 5. 原子 Commands

- `PrepareSubscriptionCycle`
  - 输入 subject、level key、source type/ref、幂等键和期望版本；
  - 校验 level active、续费规则和周期不重叠；
  - 创建 `prepared` cycle，并返回 `cycle_id`、start/end、`cycle_points_amount`；
  - 不调用任何兄弟 capability。
- `AttachPointsGrant`
  - 输入 cycle id、points entry opaque ref、幂等键；
  - 只允许 `prepared -> activated`；
  - 原子激活周期和订阅；同一 cycle 重放返回原结果，不能换绑另一条 points entry。
- `MarkCycleFailed`
  - 将未激活周期标为失败并记录稳定原因码；不得触碰 points。
- `CancelSubscription`
  - 关闭自动续费；当前周期继续有效。
- `TerminateSubscription`
  - 管理员或系统显式终止当前会员权益；不直接操作积分。
- `ExpireSubscription`
  - 持久任务把周期已结束的 active/cancelled 订阅收敛为 expired；不操作积分。

所有写操作经 Repository/UoW，产生同事务 outbox，禁止接收 Session 或执行裸 SQL。

## 6. Queries

- `ListLevels`：公开可购买等级目录。
- `GetSubscription`：subject 的当前订阅、周期与权益状态。
- `ListSubscriptions`：管理员分页，支持 subject、level、status 精确过滤。
- `GetMembershipCycle`：供 `user_center` 恢复 workflow，返回周期快照和状态。
- `ListMembershipCycles`：管理员对账与诊断。

查询不创建、续费或自动激活订阅；没有订阅时返回明确的 `no_subscription`。

## 7. user_center 装配协议

购买、礼品卡兑换或后台赠送会员都遵循同一协议：

1. `user_center` 调用 `PrepareSubscriptionCycle`，获得不可变的周期结束时间与积分额度。
2. `user_center` 调用 points `CreditPoints`：
   - program 固定为 `credit`；
   - behavior 为 `user_center.membership_cycle.credit.v1`；
   - `expires_at = membership cycle end`；
   - 幂等键包含 cycle id。
3. points 返回 entry opaque ref 后，`user_center` 调用 `AttachPointsGrant`。
4. 若第 2 步暂时失败，持久 workflow 重试；周期仍是 `prepared`，不提供会员权益。
5. 若第 2 步成功而第 3 步暂时失败，workflow 以相同幂等键查询/重放 points，再重试 attach；不得再次 credit。
6. points 到期任务在 `expires_at` 清除剩余 expiring bucket；membership 只在 end 后收敛订阅状态。

这条业务流由 kernel 持久 workflow 保存恢复点，不要求跨 capability 共用数据库事务，也不允许 membership 通过消费方 Port 偷渡业务编排。

## 8. 事件

- `membership.cycle_prepared.v1`
- `membership.activated.v1`
- `membership.renewed.v1`
- `membership.cancelled.v1`
- `membership.terminated.v1`
- `membership.expired.v1`
- `membership.cycle_failed.v1`

事件只包含 subscription/cycle、subject opaque ref、level 和周期快照；不包含 points 余额、支付金额或卡密明文。

## 9. 权限与审计

- `membership.levels.manage`：等级生命周期。
- `membership.subscriptions.read`：管理员查询。
- `membership.subscriptions.manage`：终止或修复订阅。
- 自助取消由 `user_center` 校验当前 subject 后调用 capability Command。
- 等级管理、开通、续费、取消、终止和修复全部审计。

## 10. Diagnostics 与验收

diagnostics 至少报告：

- 长时间停留在 `prepared` 的周期；
- activated cycle 缺失或使用非法 `points_entry_ref`；
- active subscription 的 end 已过期；
- 同一 subscription 的周期重叠；
- DB 等级与代码/ops 声明漂移。

验收要求：

- membership 单独装配时不需要 points/payments/identity fake Port，也不导入这些模块。
- `PrepareSubscriptionCycle` 重放不重复创建周期。
- 未 attach points entry 前用户不获得会员权益。
- `AttachPointsGrant` 重放只激活一次，且拒绝改绑 entry。
- 到期积分由 points 清理，membership 不产生 debit/expiration 流水。
- `user_center` 集成测试覆盖“points 已入账、attach 暂时失败”的恢复路径。
