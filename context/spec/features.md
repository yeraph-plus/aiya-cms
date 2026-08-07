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

- 显式用户动作触发，不由读取首页或登录等读路径隐式触发。
- 调用 points 的已注册行为 `daily_check_in.reward`。
- 幂等域为 `subject + program + local_business_date`；业务时区由行为规格显式配置。
- 奖励值、每日次数和活动窗口来自代码注册的行为规格，不执行数据库内脚本。

### 4.4 point_purchase

- 创建 payment order，等待受信 webhook 确认 captured，再调用 points credit。
- workflow 幂等键为内部 order ID；provider event ID 另有唯一约束。
- webhook 重复或乱序不得重复发放积分。
- 退款调用 points reversal，保留支付和积分原始流水。
- 价格来自代码注册的服务端受信 offer 目录（`POINT_OFFERS`），客户端只能选择 `offer_key`，不得自报金额或积分数量。

### 4.5 site_settings

- 站点级 settings 组声明集中于此：`general`（站点通用）、`seo`（结构化站点默认值）、`notification`（投递通道设置）。
- `notification` 组承载 SMTP 连接参数与凭据：host/port/username/password/from_address、use_tls/starttls 全部由 settings 填写；`smtp_password` 登记为 sensitive，不进入公共 DTO、事件、日志和审计摘要。
- settings capability 是纯被动宿主：只持久化、校验、按权限门控、发事件和提供读取；不自行声明任何组。
- 注册由组合根显式装配并 freeze；未知组、重复 key、不可序列化默认值启动失败。
- adapter 装配时从 `notification` 组读取连接配置（见 `adapters.md` §3.1）；host 未配置时拒绝绑定 SMTP adapter，不在缺配置状态下静默运行。

## 5. 示例流程的非需求声明

“待审入库 -> 通知管理员 -> 关键词过滤 -> 发布 -> 发放积分”只用于验证垂直工作流是否能在一处清晰表达，不自动成为 post 的产品行为。

如需启用，应建立单独 FeatureSpec，明确审核策略、关键词 provider、通知模板、积分行为和失败语义；不得通过全局事件订阅让这些行为隐式出现。

## 6. Feature 注册所有权

- content type 由 feature 注册，content capability 只验证和执行。
- taxonomy dimension 可由 feature 注册，taxonomy capability 只维护维度和 term 数据。
- points behavior 由 feature 注册，points capability 只执行账本规则。
- RouterSpec、workflow 和 Cron 同样由 feature 声明、api manifest 选择。
- 同一稳定 key 只能有一个 owner；重复注册必须启动失败。

## 7. 验收

- post/page 只靠声明复用 content，不复制 content ORM/Service。
- page manifest 中不存在 taxonomy 注册。
- check-in 并发请求只产生一次有效奖励。
- point purchase 在 webhook 重放、乱序、worker 重启时不重复入账。
- 示例审核流程可作为合同测试 fixture 证明每步崩溃可恢复，但未加入生产 manifest 时无运行副作用。
