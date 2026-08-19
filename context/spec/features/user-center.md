# User Center Feature 规格

> 本文件定义下一用户站发布目标。本轮只建立规格，不代表当前 runtime、migration、router、OpenAPI 或 Astro 页面已经实现。

## 1. 职责与边界

`user_center` 是认证用户自助能力与“获得积分/会员权益”流程的统一 feature。它组合 identity、assets、settings、points、membership、gift_cards、payments 和 notification 的公开 Command、Query、Activity、Port 与 DTO，不访问任何 capability 的 ORM、Repository、Session 或表。

它统一替代零散的 `check_in`、`membership_grants`、`point_purchase`、`membership_purchase`、旧 `MeService` 和相应独立 router/workflow。删除的是 feature/API 组合组件，不删除 points、membership、gift_cards、payments 等 capability 及其原子事实。

`user_center` 负责：

- `/api/v1/me` 资料、头像和安全的当前用户聚合视图；
- 每日签到并向默认积分计划入账；
- 积分余额、桶和账本的本人只读视图；
- 会员等级、当前订阅、购买、续费、取消和周期积分授予；
- 受信积分商品的法币购买；
- 卡密兑换积分或会员；
- 本人 payment order 和购买结果视图；
- 退款后的权益补偿编排。

它不负责内容下载、AI 调用等积分消费；这类流程统一进入 [`business-center.md`](business-center.md)。它也不保存法币余额、支付 attempt、provider webhook、积分余额、会员订阅或卡密状态。

## 2. 依赖与公开合同

| Capability | user_center 只使用的公开面 |
| --- | --- |
| identity | 当前 subject Query、资料更新 Command |
| assets | 头像 upload intent、finalize、稳定 URL Query |
| settings | 用户站与商品目录所需只读设置 |
| points | `CreditPoints`、`ReverseLedgerEntry`、余额/桶/账本 Query |
| membership | 等级目录、准备/绑定周期、续费、取消、终止 Query/Command |
| gift_cards | verify、reserve、commit、cancel 和兑换载荷 DTO |
| payments | 创建 CNY order、查询 order、captured/refunded 事实 |
| notification | 购买/兑换结果通知 trigger |

subject 始终来自认证 Principal，HTTP body 不接受任意 `subject_id`。所有跨能力 reference 为 opaque ID，不建跨能力外键。

## 3. 受信商品与权益声明

组合根显式注册并 freeze 以下规格；客户端不能提交金额、积分数、会员周期或 fulfillment payload：

### 3.1 `PointBundleSpec`

- 稳定 `product_key`、version、显示元数据；
- 固定 `currency=CNY` 与整数分 `price_cents`；
- 固定 `program_key=credit`、`points_amount`；
- points behavior key `user_center.point_purchase.credit.v1`；
- 可售状态、有效窗口、每主体限购策略；
- refund policy version。

### 3.2 `MembershipOfferSpec`

- 稳定 `offer_key`、version；
- 对应 active `membership level_key`；
- 固定 CNY 价格、购买/续费策略；
- 会员周期以 membership level 的受信声明为准，不由客户端覆盖；
- refund policy version。

### 3.3 `GiftCardFulfillmentSpec`

- 稳定 `fulfillment_key`、payload version；
- 类型只能为 `points_bundle|membership_offer`；
- 对应 product/offer key；
- 允许的平台、活动窗口与兑换限制。

未知、重复、版本不兼容或引用未注册目标必须在启动时 fail-fast。运行时数据库只保存必要快照和 capability 自有事实，不执行数据库脚本或表达式。

## 4. 会员周期与限时积分桶

会员周期积分由 `user_center` 编排，membership 不再直接导入或通过 Port 调用 points：

1. `PrepareSubscriptionCycle` 在 membership 创建 `prepared` 周期事实并返回 `cycle_id`、`cycle_points_amount`、`cycle_end`。
2. `user_center` 调用 points `CreditPoints`，behavior 为 `user_center.membership_cycle.credit.v1`，显式 `expires_at=cycle_end`。
3. points 将额度写入 `expiring` bucket；幂等键为 `membership-cycle:<cycle_id>`。
4. `AttachPointsGrant` 记录 points entry opaque ref 并将周期转为 activated，同时使订阅 active。

积分成功而最后一步失败时重试激活；积分尚未成功时订阅不可作为 active 权益。永久失败由人工恢复或版本化补偿 Command 处理，不伪造跨 capability 单事务。

周期结束后，points 的 bucket expiration task 清零剩余额度；membership 只收敛订阅状态，不再次扣减，避免两套到期算法。

## 5. 业务流程

### 5.1 每日签到

- workflow key：`user_center.check_in.v1`；
- 业务幂等域：`subject + credit + business_date + behavior_version`；
- 调用 `CreditPoints`，不先读余额判断；
- 重放返回 `rewarded|already_rewarded`，GET `/me` 不触发签到。

### 5.2 购买积分

1. 根据 `product_key` 读取 frozen `PointBundleSpec`。
2. 调用 payments 创建 CNY order；payments 保存价格、purpose 和 provider snapshot。
3. 只以 payments `captured` 事实启动 `user_center.point_purchase.fulfill.v1`。
4. 调用 `CreditPoints`，幂等键绑定 payment order ID。
5. 记录 fulfillment result 并通知用户。

浏览器 return/callback 页面不是支付事实；重复 webhook、轮询和 workflow 重放只入账一次。

### 5.3 购买或续费会员

1. 根据 `offer_key` 建 payments order。
2. captured 后启动 `user_center.membership_purchase.fulfill.v1`。
3. 执行第 4 节的会员周期与限时积分桶流程。
4. 只有 subscription active 后才返回已完成。

### 5.4 卡密兑换积分或会员

1. `VerifyGiftCard` 只返回安全的权益摘要。
2. `ReserveGiftCardRedemption` 以 `subject + request idempotency key` 预留。
3. 按 `GiftCardFulfillmentSpec` 调用积分入账或会员周期 workflow。
4. 权益完成后 `CommitGiftCardRedemption`；可确认未产生权益时才 `CancelGiftCardRedemption`。

feature 不解释 provider 原始 payload，不记录明文 secret。外部平台查单仍由 gift_cards provider Port 完成。

### 5.5 退款补偿

- payments 先保存受信 refund 事实；user_center 消费 `payments.refunded.v1`。
- 积分商品退款调用 `ReverseLedgerEntry`；积分已被消费时允许 points 进入 debt，不能丢弃退款事实。
- 会员退款使用版本化 policy：终止对应周期并反转该周期 grant entry；已消费额度同样可以形成 debt。
- 重复 refund 事件以 payment refund ID 幂等。

## 6. 用户 HTTP 合同

所有端点进入 `openapi.user.json`，普通浏览器经 Astro BFF 调用；除公开目录外均要求认证。

| 方法与路径 | 语义 |
| --- | --- |
| `GET/PATCH /api/v1/me` | 本人聚合资料读取/更新 |
| `POST /api/v1/me/avatar/upload-intents` | 创建头像上传 intent |
| `POST /api/v1/me/avatar/upload-intents/{id}/finalize` | finalize 并更新头像 |
| `POST /api/v1/me/check-ins` | 显式签到 |
| `GET /api/v1/me/points` | 默认 `credit` 余额和 bucket 摘要 |
| `GET /api/v1/me/points/ledger` | 本人积分账本分页 |
| `GET /api/v1/membership/levels` | 公开会员等级与 offer 摘要 |
| `GET /api/v1/me/membership` | 当前订阅/周期 |
| `POST /api/v1/me/membership/orders` | 创建购买/续费 payment order |
| `POST /api/v1/me/membership/cancel` | 取消自动续费 |
| `GET /api/v1/points/products` | 公开积分商品目录 |
| `POST /api/v1/me/points/orders` | 创建积分商品 payment order |
| `GET /api/v1/me/payment-orders/{order_id}` | 本人支付与 fulfillment 状态 |
| `POST /api/v1/me/gift-cards/redemptions` | 卡密兑换 |
| `GET /api/v1/me/purchases` | 本人购买/兑换结果聚合视图 |

创建订单、签到、兑换和所有可重试写请求要求 `Idempotency-Key`。Payment provider webhook 由 payments 的受信 callback router 接收，不置于 `/me`。

## 7. 安全、审计与错误

- 商品价格、积分数量、level、program、subject 和 fulfillment type 均服务端派生。
- payment secret、gift card secret、provider payload、头像 signed URL 不进入日志、事件或购买历史。
- 订单读取必须验证 subject；公开的 order ID 不是授权边界。
- 稳定错误至少包括 `user_center.product_unavailable`、`user_center.order_not_captured`、`user_center.fulfillment_pending`、`user_center.fulfillment_failed`、`user_center.redemption_unavailable` 和 `user_center.version_conflict`。
- 购买、兑换、退款补偿、会员终止与管理员恢复全部审计；普通本人 Query 不写审计业务表。

## 8. 验收

- `user_center` 不导入 capability 内部模块；旧零散 feature/router 不再进入 manifest 或 OpenAPI。
- 签到并发重放只产生一条 credit。
- 重复 captured/refund/gift-card 请求不重复授予或反转权益。
- 会员只有在限时 bucket 已建立后激活；周期结束只由 points expiration 扣除剩余。
- 未 captured order、伪造 return URL、客户端篡改价格/subject/amount 均不能产生权益。
- 积分退款可进入 debt；事实不因余额不足丢失。
- user OpenAPI、Astro generated client、BFF 会话和端到端 workflow 有闭合测试。
