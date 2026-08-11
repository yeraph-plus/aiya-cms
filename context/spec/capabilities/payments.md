# Payments Capability 规格

## 1. 职责

payments 管理外部支付订单、provider 尝试、受信 webhook、捕获和退款事实。首个用例是购买积分，但 payments 不导入 points，也不把积分数量写成核心支付语义。

不实现购物车、库存、物流、商品目录或通用电商平台。

## 2. 金额与订单

- 金额使用 ISO 4217 currency + 最小货币单位整数，禁止浮点数。
- feature 提供不可变 purchase snapshot：offer key/version、description、amount、currency 和业务 metadata。
- 服务端计算/选择受信价格；不得接受客户端自行声明应付金额或积分数量。
- order 具有内部 UUIDv7 和公开不可猜测 reference；provider ID 不是本地主键。

## 3. 表所有权

- `payment_orders`：subject ref、offer snapshot、amount/currency、provider、state、idempotency key、expires、captured/refunded amount。
- `payment_attempts`：order、provider reference、attempt、state、request digest、错误类别和时间。
- `payment_webhook_receipts`：provider、event ID、payload digest、verified time、processing state、关联 order。
- `payment_refunds`：order/provider refund reference、amount、state、idempotency key、reason 和时间。

subject 是 opaque reference。provider 原始敏感 payload 默认不长期保存；如为争议处理必须保存，需加密、访问控制和明确短期保留策略。

## 4. 状态机

订单至少支持：

```text
created -> pending -> captured
   |          |          |
   +------> cancelled     +-> partially_refunded -> refunded
              |
              +-> failed
```

实际 provider 的 requires_action 等状态归一化到明确扩展状态。只有受信服务端返回或验签 webhook 可以把订单置为 captured/refunded；浏览器 return URL 不能作为付款事实。

## 5. PaymentProvider Port

payments 声明：

- create/confirm payment session。
- query payment status。
- verify and parse webhook。
- create/query refund。

adapter 负责 SDK、credential、签名算法、timeout、provider idempotency、错误归一化和 API version。provider-specific payload 不得进入公开 Payment DTO 或 points。

具体 provider 由部署在 provider 合同冻结后显式选择；选择只新增 adapter/config 和 provider 合同测试，不改变 payments/points 核心模型。

## 6. Commands 与 webhook

管理员运行态接口直接导出 payments capability 的语义读写面：

- `GET /api/v1/admin/payments/orders`：按 state、provider、subject 过滤并分页读取订单。
- `GET /api/v1/admin/payments/orders/{order_id}`：读取订单及其 attempt/refund 摘要，不返回 provider 原始 payload。
- `POST /api/v1/admin/payments/orders/{order_id}/cancel`：调用 `CancelPaymentOrder`。
- `POST /api/v1/admin/payments/orders/{order_id}/reconcile`：调用 `ReconcilePaymentOrder`。
- `POST /api/v1/admin/payments/orders/{order_id}/refund`：调用 `RequestRefund`。

管理端不提供万能更新或删除订单接口；状态变化只能通过上述 Command 和已验签 webhook 发生。

- `CreatePaymentOrder`
- `StartPaymentAttempt`
- `CancelPaymentOrder`
- `ProcessVerifiedWebhook`
- `ReconcilePaymentOrder`
- `RequestRefund`

webhook 入口必须先基于原始 bytes、签名 header、时间窗和 provider secret 完成验签，再解析业务字段。`(provider, event_id)` 唯一；重复 receipt 返回已处理结果。

未知订单、乱序状态、金额/币种不匹配进入隔离/诊断，不猜测成功。捕获和 `payment.captured.v1` outbox 在同一 UoW 提交。

## 7. 幂等和失败

- `(provider, order idempotency key)` 唯一，重复创建不产生第二笔应付订单。
- 订单读取 DTO 携带本地 idempotency key，供 workflow 桥接按 `(workflow key, idempotency key)` 定位等待中的实例；它不携带 provider-specific payload。
- 调 provider 时传稳定 idempotency key（若支持）。
- 请求超时结果不明时标记 unknown/pending 并查询 provider，不盲目再创建支付。
- webhook 可重复、延迟和乱序；状态转换必须单调或由明确 reconciliation 纠正。
- refund 以本地 refund idempotency key 和 provider reference 去重。

## 8. Events

- `payment.order_created.v1`
- `payment.pending.v1`
- `payment.captured.v1`
- `payment.failed.v1`
- `payment.cancelled.v1`
- `payment.refund_completed.v1`

事件包含本地 order、subject、offer reference、受信 amount/currency 和 provider reference 摘要，不包含卡号、client secret、签名或原始 webhook。

point_purchase feature 消费 captured/refund 事实并调用 points；payments 不关心发放结果。积分发放失败不会把已捕获支付伪装成失败，workflow 必须持续重试/人工恢复。

## 9. 安全、审计和 diagnostics

- 所有支付端点要求 TLS；provider secret 只来自 secret provider。
- 限制 webhook body 大小、Content-Type、时间窗和速率。
- 审计订单状态改变、reconcile、退款和管理员操作，不记录敏感支付数据。
- diagnostics 检查长期 pending/unknown、captured 金额不一致、未处理 verified webhook、退款不一致和 provider 连接状态。

## 10. 验收

- 伪造签名、过期签名、payload 修改和重放被拒绝或幂等处理。
- 浏览器 return/callback 不能直接置 captured。
- 创建/捕获/退款在超时、重复和乱序场景保持单一事实。
- captured 事件与订单状态原子提交。
- point issuance 失败不改变 payment captured；恢复后只发一次积分。
- payments 在不导入 points/identity 的情况下通过合同测试。
