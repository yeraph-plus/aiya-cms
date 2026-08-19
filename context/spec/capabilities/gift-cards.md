# Gift Cards Capability 规格

## 1. 范围与非目标

`gift_cards` 是礼品卡/卡密的发行、查验、预留和核销事实能力。它只负责卡密生命周期、来源平台适配、外部购买事实去重和兑换凭证输出；不负责把礼品卡兑换成会员或积分。

当前实现只覆盖 capability 的卡密发行、查验、预留、提交/取消事实、迁移与管理员 HTTP 适配。下一用户站 release 由 `user_center` 实现兑换积分/会员的 feature 链；真实外部网络 provider 仍需按 adapter 规格单独实施和验收。

礼品卡兑换会员、积分或未来其他权益属于 `user_center`：它根据卡密返回的 `fulfillment_key` 和版本化权益载荷调用 membership、points 等公开 Command。`gift_cards` 不导入 payments、membership、points、identity 或其他兄弟 capability。

## 2. 核心不变量

- 一张卡只有一个 `secret`，不存在“卡号 + 密码”两段式输入，也不接受把两段字段拼接成兼容格式。
- 系统生成的卡密使用 CSPRNG 产生，明文只在生成/安全导出时返回一次；数据库只保存带服务端 pepper 的不可逆 digest，日志、事件、审计和错误中禁止出现明文。
- 外部赞助平台的订单号/交易号就是礼品卡 `secret`。它不是本系统生成的卡密，不预先插入 `gift_cards`；首次查单成功后才建立外部凭证和兑换事实。
- 每个内部卡或外部凭证均绑定 `platform_key`、`product_key`、权益载荷版本和来源凭证。provider 切换只影响未绑定的新购买/查验，不重新解释已核销事实。
- 同一 secret 在同一平台只能成功兑换一次。并发兑换必须通过 capability 自己的状态机和唯一约束收敛，不能由 feature 先查后写。
- 外部平台的“已付款/可兑换”事实以 adapter 查单或验签后的回调为准；浏览器跳转、用户自行提交的订单号和未经验证的回调都不是兑换事实。
- 失败、过期、撤销和已兑换均返回稳定错误码，不泄露“该 secret 是否存在”以外的敏感信息；对外验证接口应对不存在、未付款和无权限使用统一的安全响应。

## 3. 来源平台与平台切换

组合根为 `gift_cards.provider` 注册所有允许的平台实现，注册工厂不得连接外部服务。计划中的稳定 provider key 为：

- `card_platform`：外部发卡/商品平台。购买商品后由平台回调或查单，能力从可用批次分配一条本系统生成的卡密。
- `afdian`：爱发电赞助平台。使用平台订单号作为 secret，通过订单查单确认赞助方案/商品和成功状态；回调仅作为可选加速路径，不能替代查单事实。
- `patreon`：Patreon 赞助平台。使用平台订单号/交易号作为 secret，通过 Patreon 适配器查验创作者、活动、等级/商品和支付状态；具体字段以 adapter 对 Patreon API 合同的映射为准。

settings 只保存当前默认 provider 和各 provider 的只读配置快照；未知 key、未注册 provider 或 provider 缺配置时 fail-fast/typed unavailable。运行时不按顺序尝试多个 provider，不因查不到 secret 而静默切换平台。

购买请求在创建时保存 `platform_key`。内部生成卡和已经建立的外部凭证永远按记录中的平台解析；对尚未绑定的外部 secret，调用方必须提供平台上下文或使用 settings 当前默认 provider。切换 provider 不会迁移、删除或重新签发既有卡密。

## 4. 数据所有权与模型

以下表均归 `gift_cards` capability；字段名是稳定语义，具体 ORM 类型可在实现时选择，但不得把跨能力表建为外键或 relationship。

### 4.1 `gift_card_batches`

批量生成批次：

- `id`、`batch_key`、`platform_key`、`product_key`；
- `fulfillment_schema_version` 与 `fulfillment_payload`（JSONB，版本化且由发行方校验）；
- `quantity`、`generated_count`、`expires_at`、`status`（`active`/`closed`/`revoked`）；
- `idempotency_key`、`created_by` opaque subject、`created_at`、`closed_at`。

一个批次只能生成一次确定数量的卡密；重复 idempotency key 返回原批次，不重复发卡。批次关闭后不能再分配或重新打开。

### 4.2 `gift_cards`

只保存本系统生成的卡密：

- `id`、`batch_id`、`platform_key`、`secret_digest`（唯一）；
- `status`（`issued`/`reserved`/`redeemed`/`revoked`/`expired`）；
- `redemption_id`、`reserved_until`、`redeemed_at`、`revoked_at`、`created_at`。

明文 secret 不落库、不进入 `gift_card_batches` 的 JSONB、不进入 outbox。批量导出必须是一次性、受权限保护的安全结果；导出后不能再次读取原文。

### 4.3 `gift_card_external_claims`

外部平台凭证的本地幂等和状态锚点：

- `id`、`platform_key`、`external_order_digest`（与平台 key 组成唯一键）；
- `product_key`、`fulfillment_schema_version`、`fulfillment_payload`；
- `provider_fact_digest`、`provider_status`、`verified_at`、`expires_at`；
- `redemption_id`、`created_at`、`updated_at`。

外部订单号原文只在一次查单调用中使用，默认不持久化；如 provider 合同要求审计原文，必须使用独立加密密钥和最小保留期，不能把它当作普通卡密明文保存。

### 4.4 `gift_card_redemptions`

兑换状态机和 feature 的幂等锚点：

- `id`、`source_kind`（`internal`/`external`）、`source_id`、`platform_key`；
- `subject_type`、`subject_id` opaque reference；
- `fulfillment_schema_version`、`fulfillment_key`、`fulfillment_payload` 快照；
- `status`（`reserved`/`committed`/`cancelled`/`expired`）、`idempotency_key`；
- `reserved_until`、`committed_at`、`cancelled_at`、`created_at`。

`source_id + status` 的唯一/排他约束必须保证一个来源只能有一个有效兑换。`fulfillment_payload` 是兑换时的不可变快照，不是对 membership 或 points 表的复制。

## 5. 公开 Command、Activity 与 Query

### 5.1 Commands

- `GenerateGiftCardBatch`：管理员按数量、`product_key`、权益载荷、过期时间批量生成内部卡密；输入必须有幂等键和版本；返回批次摘要及一次性明文导出句柄/结果。
- `CloseGiftCardBatch`：关闭批次，阻止继续发卡；不物理删除已发出的卡。
- `RevokeGiftCard`：管理员撤销尚未兑换的内部卡，要求原因、权限、审计和乐观并发。
- `ReserveGiftCardRedemption`：输入单一 secret、subject opaque reference、平台上下文和幂等键；对内部卡校验本地 digest，对 Afdian/Patreon 等外部平台执行查单/验签，写入 `reserved` 兑换并返回权益快照。
- `CommitGiftCardRedemption`：feature 完成会员/积分等下游动作后提交兑换；只接受相同 redemption 和幂等键。
- `CancelGiftCardRedemption`：下游不可恢复失败或补偿流程释放预留；已 committed 的兑换不可取消。
- `RecordProviderPurchase`：将已验签的发卡平台商品事实绑定到批次/产品并分配卡密；同一 provider 事实重复到达必须幂等。
- `RecordProviderWebhook`：接收 adapter 验签后的标准事实，按 provider/order 唯一键去重；原始回调不直接写业务表。

### 5.2 Activities / Workflow 步骤

外部查单、验签、分配卡密和回调确认都必须是可重试、可观测、带幂等键的 Activity。不得在持有数据库事务或锁时等待 provider 网络。需要跨能力完成权益发放时，由 `user_center` 的持久 feature workflow 编排：

```text
ReserveGiftCardRedemption
        ↓
调用 membership / points 公开 Command 或 Port
        ↓
CommitGiftCardRedemption
```

workflow 重试必须复用 redemption/idempotency key；不能因为下游超时再次生成卡密或再次授予权益。

### 5.3 Queries

- `GetGiftCardBatch`、`ListGiftCardBatches`：管理员查询批次摘要、数量、状态和失败统计，不返回 secret。
- `GetRedemption`：管理员/审计按 redemption id 查询状态和权益快照。
- `VerifyGiftCard`：面向 `user_center` 的验证入口，输入只含一个 secret 和平台上下文，返回通用的 `valid`/`invalid` 结果、来源平台、产品 key 和可兑换权益摘要；不创建兑换、不返回 provider 原始响应。

验证若需要外部查单，必须通过带超时和限流的 Activity/Port；不得把 provider 网络调用塞入无副作用 Query 或 HTTP handler。

## 6. Platform Port 合同

`GiftCardPlatformPort` 是 `gift_cards` capability 消费的 Port；adapter 实现在 `inc/adapters/gift-cards/`，capability 不导入 adapter。所有方法接收不可变 settings snapshot，不得读取环境变量或 ORM。

```text
check_availability(snapshot) -> Availability
start_purchase(request) -> PurchaseSession | unsupported
lookup_purchase(secret, context) -> ProviderPurchaseFact
verify_webhook(request) -> ProviderPurchaseFact
acknowledge_webhook(fact) -> None
```

统一 DTO 至少包含：

- `platform_key`、`external_order_id`（仅内存/受保护边界使用）、`provider_fact_id`；
- `paid`、`product_key`、`fulfillment_schema_version`、`fulfillment_payload`；
- `occurred_at`、`expires_at`、`idempotency_key`。

`start_purchase` 仅对支持创建商品订单的 provider 有效；Afdian/Patreon 默认不由本系统创建订单，返回 `unsupported` 或由 adapter 根据平台规定实现。`lookup_purchase` 是 Afdian/Patreon 的权威路径，必须校验 creator/campaign、产品/等级映射、付款状态和重复使用。

Webhook 请求统一为 `method`、raw body、headers、query parameters；adapter 先验签、规范化和脱敏，随后 capability 才能记录事实。provider 原始 headers、access token、签名密钥和 SDK 异常不得进入公开 DTO、日志或事件。

## 7. 平台差异化规则

### 7.1 `card_platform`

- 商品平台的购买事实由回调或查单确认，回调中只传 provider order id、商品 key、数量和支付状态等标准字段。
- capability 只从指定批次分配内部生成的 secret；同一订单和同一张卡的分配必须幂等。
- provider 不可用、商品未配置、数量不匹配或回调验签失败均不得分配卡密。

### 7.2 `afdian`

- secret 为 Afdian 订单号；系统不生成替代卡密，也不要求卡号/密码。
- 验证流程必须查询 Afdian 订单，确认订单成功、方案/商品映射和未兑换状态；订单号本身不是付款事实。
- webhook 若可用只负责缩短等待或触发重查，最终状态仍由查单结果确认；`out_trade_no` 重放只能产生一个 external claim/redemption。
- 现有 `inc/adapters/gift-cards/afdian.py` 源码作为独立 SDK 保留，但未来礼品卡 adapter 需实现 `GiftCardPlatformPort`，不得把该 SDK 直接暴露成 payments provider 或让 capability 反向导入它。

### 7.3 `patreon`

- secret 为 Patreon 适配器合同规定的订单号/交易号；不在本系统重新生成或改写。
- 查单必须绑定目标 creator/campaign，并校验 tier/商品、付款状态、撤销/退款状态和兑换期限。
- 回调与周期性查单都要按 provider 事件/订单唯一键幂等；平台撤销或退款不得自动回滚已提交的下游会员/积分，需由后续明确的 feature/补偿策略处理。

## 8. 权限、错误与审计

计划中的稳定权限 key：

- `gift_cards.batch_generate`
- `gift_cards.manage`
- `gift_cards.verify`
- `gift_cards.redeem`
- `gift_cards.reconcile`

稳定错误码至少包括：

- `gift_cards.provider_unavailable`、`gift_cards.unknown_provider`；
- `gift_cards.invalid_secret`、`gift_cards.provider_not_paid`、`gift_cards.product_not_eligible`；
- `gift_cards.already_redeemed`、`gift_cards.revoked`、`gift_cards.expired`；
- `gift_cards.redemption_conflict`、`gift_cards.idempotency_conflict`；
- `gift_cards.webhook_invalid`、`gift_cards.webhook_replayed`、`gift_cards.rate_limited`。

批量生成、撤销、外部事实绑定、预留、提交、取消和人工对账均写审计事件。事件只含 digest、provider key、产品 key、状态和 opaque id，不含 secret、订单原文或 provider 凭据。

## 9. 设置与 provider 可用性

未来 settings capability 增加 `gift_cards` 组，至少包含：

- `provider`：`card_platform`、`afdian`、`patreon`；
- provider endpoint、creator/campaign、商品/方案到 `product_key` 的映射；
- 回调验签公钥/secret、请求超时、查单重试和兑换期限；
- 敏感凭据字段必须标记 sensitive，公开设置不得返回。

设置描述不包含 title、desc、label 等展示文本，只保留 slug、type、默认值、敏感性、公开性、选项值和结构约束。provider 只在显式检查或购买/验证调用时建立短生命周期客户端；启动注册不得发起网络请求。

## 10. 事件与迁移

计划事件 key：

- `gift_cards.batch_created.v1`
- `gift_cards.batch_closed.v1`
- `gift_cards.provider_purchase_recorded.v1`
- `gift_cards.redemption_reserved.v1`
- `gift_cards.redemption_committed.v1`
- `gift_cards.redemption_cancelled.v1`
- `gift_cards.card_revoked.v1`

表、事件 schema、权限和管理员 OpenAPI 由 capability 自己拥有并加入统一 migration manifest；下一用户站只通过 `user_center` 暴露积分/会员兑换端点。真实外部 provider、worker 或 Cron 是否装配，以对应 adapter 完成合同测试并进入 release manifest 为准。

## 11. 验收合同

- 单 secret 生成、一次性导出、digest 存储、日志/事件脱敏和批量幂等。
- 同一内部卡并发兑换只能成功一次；预留过期、取消和提交状态机可恢复。
- Afdian/Patreon 订单号作为 secret 查单；未付款、错误 creator/tier、退款/撤销、重复查单均不能兑换。
- 发卡平台回调验签、查单、重复回调、数量分配和 provider order 幂等。
- provider 切换不回退、不广播查询、不重解释已绑定卡；缺配置和网络失败返回安全 reason。
- capability 不导入 payments、membership、points、identity 或 adapter；`user_center` 只消费公开 DTO/Command/Activity/Port。
- 未完成本规格对应的失败测试、迁移、feature workflow、OpenAPI 和端到端验证前，不得宣称卡密兑换积分/会员已经交付。
