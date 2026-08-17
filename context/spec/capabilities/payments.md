# Payments Capability 规格

## 范围

payments 是订单、attempt、受信 webhook receipt 和退款的原子 capability，不导入 points、membership 或 identity。release 仅保留 PayPal/Epay Port 合同及闭合测试；不暴露购买、支付回调、退款或管理 HTTP 路由。

## 金额与状态

唯一 currency 常量是 `CNY`。订单、状态查询、webhook、退款和事件均验证 CNY；金额为整数分，禁止浮点、币种设置和转换。PayPal 出站请求恒为 `CNY`，由 PayPal 侧处理换算。币种或金额不匹配不得捕获订单，而是隔离/诊断。

订单/attempt/webhook receipt/refund 使用 provider 与业务幂等键去重。只有验签通过的 provider 事实可把订单置 captured/refunded；浏览器 return URL 永远不是付款事实。捕获和 outbox 事件同一 UoW 提交。

## Port

PaymentProvider 包含创建 session、查询状态、验证 webhook、创建/查询退款和 `check_availability()`。`ProviderSession` 标准化为可选 `redirect_url`、`qr_code_payload`、`app_url`，至少必须有一个可供下一步动作。`WebhookRequest` 始终含 method、raw body、headers、query parameters；provider 专有原始 payload 不进入公开 DTO。

缺少 provider settings、凭据失效或连接失败时 adapter 返回安全 reason，capability 对业务调用给出 `payments.provider_unavailable`；不得泄露 merchant key、client secret 或 SDK 原文。

## Epay

Epay adapter 使用 LemPay 兼容协议：`mapi.php` form 提交/JSON 响应；排序、过滤 `sign`/`sign_type`/空值/`0` 后追加商户密钥的小写 MD5；GET webhook 验签、`TRADE_SUCCESS` 状态与字面 `success` ACK；`api.php` 查询、退款端点。HTTP mock 覆盖下单、签名、webhook、重放幂等、查询、退款、金额和 CNY 负例，不发真实支付。

## 验收

- 开发 fake provider 不存在，catalog 始终同时注册 PayPal、Epay。
- 金额或 CNY 不匹配不能改变订单事实；重复 webhook 不重复处理。
- 启动不探测支付 provider；显式检查/调用才返回安全 unavailable。
