# 垂直 Feature 规格

## 1. 定位

feature 是应用实际业务规格和跨能力流程的承载层。capability 提供可复用能力，feature 决定本系统如何组合它们。

feature 可以在一个文件内完整声明业务顺序、分支、重试、信号和补偿，但只能调用 capability 的公开 Command/Query/Activity/Port，不直接操作其表。

## 2. 目录合同

```text
inc/features/<name>/
  definition.py          # FeatureSpec 与静态注册
  workflows/             # 跨事务流程；一个主流程一个文件
  api.py                  # 可选 RouterSpec
  schemas.py              # feature 输入输出 DTO
  tests/
```

简单声明型 feature 可以只有 `definition.py`。只有在出现独立持久化模型和通用生命周期后，才把它提升为 capability。

## 3. 工作流规则

- workflow 输入和持久化状态必须是版本化 Pydantic 模型。
- 每一步是有稳定 key 的 activity，必须声明超时、重试类别和幂等键策略。
- 每个 activity 单独提交；禁止把等待审核、外部 SDK 或多能力写入放入一个数据库事务。
- 等待人工/外部结果使用持久化 signal，不占用线程或长事务。
- workflow 重放不得读取不受控的当前时间、随机数或网络；这些值由 activity 产出并持久化。
- 发布、发信、扣积分等不可逆事实完成后，后续失败不得伪造回滚。
- compensation 只用于有真实反向操作的步骤，并保留原事实和审计。

## 4. 初始 features

### 4.0 content_engagement

- 依赖 `content` 与 `engagement`，消费 content 事实事件并调用 engagement 的公开投影 Command。
- 不持有业务表，不直接访问任何 ORM；投影重建和事件重放必须可恢复、幂等。

### 4.1 post

- 注册 `post` content type。
- 注册 `category` 和 `tag` taxonomy dimensions：category 默认单选，tag 多选。
- 提供内容管理所需 RouterSpec，但最终是否挂载由 manifest 决定。
- post 本身不自动发邮件、关键词过滤或奖励积分；这些行为只有在单独 workflow feature 明确注册后才生效。

### 4.2 page

- 只注册 `page` content type。
- 不注册 taxonomy dimension，不实现父子页面。
- 使用 content capability 的草稿、发布、定时发布、归档和置顶能力。
- 前端负责页面路由和单页 SEO 组合，后端不保存路由树。

### 4.3 check_in

- 显式用户动作触发，不由读取首页或登录等读路径隐式触发。HTTP 触发点为 `POST /api/v1/check-in`（需认证，无需额外权限）；业务日期在请求时刻按行为规格的业务时区固定。
- 调用 points 的已注册行为 `daily_check_in.reward`。
- 幂等域为 `subject + program + local_business_date`；业务时区由行为规格显式配置。
- 奖励值、每日次数和活动窗口来自代码注册的行为规格，不执行数据库内脚本。
- 用户摘要 `GET /api/v1/me`（需认证）包含当前 subject 默认 `credit` program 的 points 余额；尚未发生积分写入时返回稳定空结果，读路径不开户。积分流水通过 `GET /api/v1/me/points/ledger` 分页读取。

`/api/v1/me` 的跨 capability read model 以及头像上传完成后的 identity + assets workflow 编排由 check_in feature gateway 承载；HTTP router 只负责认证、参数和响应映射。

### 4.4 point_purchase

- 创建 payment order，等待受信 webhook 确认 captured，再调用 points credit。
- workflow 幂等键为内部 order ID；provider event ID 另有唯一约束。
- webhook 重复或乱序不得重复发放积分。
- 退款调用 points reversal，保留支付和积分原始流水。
- 价格来自代码注册的服务端受信 offer 目录（`POINT_OFFERS`），客户端只能选择 `offer_key`，不得自报金额或积分数量。
- HTTP 端点：`GET /api/v1/point-purchase/offers`（需认证）返回受信目录；`POST /api/v1/point-purchase/orders`（需认证 + `Idempotency-Key` 头）启动购买 workflow 并返回 order reference 与 checkout URL，重复键返回原结果；`POST /api/v1/admin/payments/orders/{order_id}/refund`（`payments.refund` 权限）发起退款。
- webhook 桥接：`POST /api/v1/webhooks/payments/{provider_key}` 验签去重后，captured 事实经 `(workflow key, order idempotency key)` 只读查找定位等待中的购买 workflow 并投递 capture signal；refund 完成事实启动退款 workflow 并投递 refund signal；duplicate receipt 不重复桥接。

### 4.5 site_settings

- 站点级 settings 组声明集中于此：`general`（站点通用）、`seo`（结构化站点默认值）、`notification`（投递通道设置）、`object_storage`（S3-compatible 资产存储）、`entitlements`（权益数值）、`operations`（审计和自动执行日志保留策略）。
- `notification` 组承载 SMTP 连接参数与凭据：host/port/username/password/from_address、use_tls/starttls 全部由 settings 填写；`smtp_password` 登记为 sensitive，不进入公共 DTO、事件、日志和审计摘要。
- `entitlements` 组承载业务流发放积分的可配置数值：`registration_reward`（注册奖励）、`invite_reward`（邀请奖励）、`gift_quota`（赠送额度），全部为整数积分。积分发放行为（注册/邀请/赠送 feature）从该组读取数值后作为固定金额调用 points behavior；entitlements 组本身只存数值，不执行任何积分逻辑。
- settings capability 是纯被动宿主：只持久化、校验、按权限门控、发事件和提供读取；不自行声明任何组。
- `object_storage` 组的 S3 access key/secret key 是 sensitive 字段，只有 adapter 的私有读取可消费；`s3_bucket` 为系统资源 bucket，`s3_avatar_bucket` 为用户头像 bucket；公共读取、事件、日志和审计摘要不得包含凭据。
- 注册由组合根显式装配并 freeze；未知组、重复 key、不可序列化默认值启动失败。
- adapter 每次投递时从 `notification` 组读取连接配置（见 `adapters.md` §3.1）；host 未配置时拒绝该次 SMTP 投递，不在缺配置状态下静默运行。

### 4.6 membership_purchase

- 组装 payments + membership + points：受信价格目录（`MEMBERSHIP_OFFERS`，offer key -> 金额/币种/level key）→ payment order → 受信 capture 事实 → `SubscribeLevel` → 经 PointsLedger Port 授予积分（expiring 桶，`expires_at = 订阅周期结束时刻`）。
- 该 feature 同时声明 membership level specs 与 points behavior `membership.grant`（credit，`allowed_source_types=("membership",)`）。
- 幂等：workflow 与 payment order 共享业务 idempotency key（`membership:<key>`）；重复 capture 事件不重复开通；重复 Idempotency-Key 请求返回原 checkout 视图。
- HTTP 端点：`GET /api/v1/membership-purchase/offers`（需认证）返回受信目录；`POST /api/v1/membership-purchase/orders`（需认证 + `Idempotency-Key` 头）启动购买 workflow 并返回 order reference 与 checkout URL。
- webhook 桥接：captured 事实经 `(workflow key, order idempotency key)` 只读查找定位等待中的购买 workflow 并投递 capture signal；非 captured 或非本 feature 的订单忽略。
- 会员退款流程未定义（首版不实现 membership refund workflow）；退款仅适用于 point_purchase。

### 4.7 site_cleanup

- 声明 `site.cleanup.retention.v1` Cron，并由 kernel `CronScheduler` 生成持久 task instance。
- 读取 `site_settings.operations.audit_retention_days`，清理超过策略期限的 audit entry、已投递/dead outbox、成功 inbox receipt 和终态 task instance。
- 清理由显式 activity 执行；audit capability 在同一 activity 中写入独立的 `audit.retention.cleaned` 摘要，不通过 GET、diagnostics 或 CLI 隐式修改记录。
- 不拥有 content 定时发布、points 桶过期、membership 到期或 OIDC signing key 清理的业务状态机；这些 capability-native handler 由组合根按 capability 装配。site_cleanup 只负责日志/记录保留清理。

## 5. 示例流程的非需求声明

“待审入库 -> 通知管理员 -> 关键词过滤 -> 发布 -> 发放积分”只用于验证垂直工作流是否能在一处清晰表达，不自动成为 post 的产品行为。

如需启用，应建立单独 FeatureSpec，明确审核策略、关键词 provider、通知模板、积分行为和失败语义；不得通过全局事件订阅让这些行为隐式出现。

## 6. Feature 注册所有权

- content type 由 feature 注册，content capability 只验证和执行。
- taxonomy dimension 可由 feature 注册，taxonomy capability 只维护维度和 term 数据。
- points behavior 由 feature 注册，points capability 只执行账本规则。
- membership level 由 feature 注册（`level_specs`），membership capability 只校验和执行订阅规则。
- RouterSpec、workflow 和 Cron 同样由 feature 声明、api manifest 选择。
- 同一稳定 key 只能有一个 owner；重复注册必须启动失败。

## 7. 验收

- post/page 只靠声明复用 content，不复制 content ORM/Service。
- page manifest 中不存在 taxonomy 注册。
- check-in 并发请求只产生一次有效奖励。
- point purchase 在 webhook 重放、乱序、worker 重启时不重复入账。
- membership purchase 在 webhook 重放时只开通一次订阅并只授予一次积分。
- entitlements 组数值由业务 feature 读取后以固定金额调用 points，组本身不执行积分逻辑。
- 示例审核流程可作为合同测试 fixture 证明每步崩溃可恢复，但未加入生产 manifest 时无运行副作用。
