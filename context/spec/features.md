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

## 4. 产品 features

完整产品 manifest 的跨能力用户业务装配 `auth`、`user_center`、`post`、`page`；`site_settings` 和 `site_cleanup` 是独立站点/运维 feature。community 是拥有自身模型、表、Command/Query 和 RouterSpec 的独立 capability，不为了“产品页面”再包一层同名 feature。只有通知、积分奖励等真实跨 capability 流程出现时，才新增 owner 明确的 feature。详细用户站、路由和部署合同见 [`用户站基础框架规格`](<../user site spec/user-site.md>)。

### 4.1 auth

- 依赖 identity、access 和 notification，承载注册、邮箱验证、密码找回和密码重置的多步业务流；HTTP router 只负责协议解析、限流、授权依赖和响应映射。
- 注册在同一 identity/access UoW 中创建主体并分配默认用户角色，提交后才通过 notification Port 发送验证挑战；发送失败不得回滚已提交主体事实。
- 密码找回只产生一次性挑战，验证挑战后才允许重置凭据；挑战发送和校验使用 capability 的公开 Command/Query，不直接访问 ORM/Repository。
- feature 未装配时不得产生注册、验证、找回或重置路由及通知副作用。

### 4.2 user_center

- 依赖 identity、assets、points、payments、membership，组装当前用户资料/头像、签到、积分购买、会员购买和本人购买记录；不拥有这些 capability 的表、ORM 或 Repository。
- `/api/v1/me` 的跨 capability read model 以及头像上传完成后的 identity + assets workflow 由 `user_center` gateway 承载；HTTP router 只负责认证、参数和响应映射。
- 签到必须由 `POST /api/v1/me/check-ins` 显式触发，不由首页、登录或任何 GET 隐式触发。调用 behavior `daily_check_in.reward`；幂等域为 `subject + program + local_business_date`，业务时区在请求时固定。
- 积分购买使用服务端 `POINT_OFFERS` 快照：创建 payment order，等待受信 captured 事实后调用 `purchase.completed.credit`；退款调用 points reversal 并保留原支付/积分事实。
- 会员购买使用 `MEMBERSHIP_OFFERS` 与注册的 level specs：payment captured 后调用 `SubscribeLevel`，再经 membership 的 PointsLedger Port 使用 `membership.grant` 授予到期积分。
- 购买 workflow 与 payment order 共享业务 idempotency key；provider event ID 另有唯一约束。重复/乱序 webhook、worker 重启和客户端重试不得重复发放积分或开通订阅。
- 继续使用稳定 workflow key `checkin.reward.v1`、`pointpurchase.purchase.v1`、`pointpurchase.refund.v1`、`membershippurchase.purchase.v1`。feature 包移动不改变 key；语义破坏性变化新增版本。
- 会员退款流程首版仍未定义；退款只适用于 point purchase。

### 4.3 post

- 注册 `post` content type，固定 `body_format=markdown`、`body_profile=gfm-v1` 和 524288 UTF-8 byte 上限，以及 `category` 单选和 `tag` 多选 taxonomy dimensions。
- post slug 由 content 的 `generated_title_suffix_v1` 策略在创建时生成，作为 Astro `GET /posts/{slug}` 的唯一公开文章路由键；用户侧 URL 不暴露 UUID，标题编辑不改变 slug。
- post 的基础列 `excerpt` 是列表摘要与 SEO fallback 的唯一来源；目标 `PostData` 不再声明 `summary`，也不建立双写兼容逻辑。
- post 的 Pydantic data schema 可以声明类型化 SEO 编辑覆盖值；它只提供事实输入，最终 canonical/head/JSON-LD/sitemap 由 Astro 用户站生成。
- 为 content 的 `ContentPublicationPolicy` Port 绑定 post 发布策略：submit/schedule/publish 前要求非空正文、非空 excerpt，并通过 assets 公开 Query/`AssetExists` Port 验证 Markdown `asset:<uuid>` 引用均为 ready。该绑定不允许 content 导入 assets，post 也不得访问两者 Repository。
- 拥有用户侧 post RouterSpec，并通过 content/taxonomy 的公开 Query 组成 published 列表与详情 DTO；通用 `/content/{type_name}` 用户 router 不进入完整产品 manifest。
- 组装 engagement：消费带 content version 的事实事件并调用 engagement 投影 Command，注册 post 的 views/like/rating/favorites 路由；投影重建和事件重放必须可恢复、幂等。
- 组装 comments：为 comments 的 `TargetExistsPort` 绑定只接受 published/存在 post 的策略，注册 post nested 评论读取/提交路由。comments 的表、审核状态机和管理员审核 RouterSpec 仍归 comments capability。
- 不自动发邮件、关键词过滤或奖励积分；这些行为只有新的显式 workflow 声明并进入 manifest 后才生效。
- 不直接访问 content、taxonomy、engagement 或 comments 的 ORM/Repository。跨 capability 组合需要批量效率时，扩展公开 Query/readmodel Port，不在 router 中跨表 join。

### 4.4 page

- 只注册 `page` content type 和独立公开只读 RouterSpec；slug 使用 `generated_title_suffix_v1`，正文固定使用与 post 相同的 `gfm-v1`/UTF-8 byte/资源引用合同。
- page 的 Pydantic data schema 可以声明与 post 同合同的类型化 SEO 编辑覆盖值；不得保存最终 HTML、XML、robots 文本或前端路由树。
- 为 content 的 `ContentPublicationPolicy` Port 绑定 page 发布策略：submit/schedule/publish 前要求非空正文、非空 excerpt 和所有 Markdown asset ready；不增加跨 capability 外键或 ORM relationship。
- 不注册 taxonomy dimension，不装配 engagement 或 comments，不实现父子页面。
- 使用 content capability 的草稿、发布、定时发布、归档和置顶能力。
- Astro 负责页面 URL、`robots.txt`、sitemap 和 SSR head/JSON-LD；后端不保存路由树或生成最终 SEO 文档。

### 4.5 site_settings

- 站点级 settings 组声明集中于此：`general`（站点通用）、`seo`（结构化站点默认值）、`notification`（投递通道设置）、`object_storage`（S3-compatible 资产存储）、`payments`（启用 payments capability 时的已注册 provider 选择）、`entitlements`（权益数值）、`operations`（审计和自动执行日志保留策略）。
- `GET /api/v1/site` 只投影 allowlist 内 `public=true && sensitive=false` 的发布值、类型化 SEO 输入和公开 feature 摘要；不导出最终 head/XML/robots 文本、私有值、sensitive metadata 或管理员字段 schema。
- `notification` 组承载 SMTP 连接参数与凭据；password/API key 登记为 sensitive，不进入公共 DTO、事件、日志和审计摘要。
- `entitlements` 组只保存 registration/invite/gift 等固定积分数值；业务 feature 读取后调用 points behavior，settings 不执行积分逻辑。
- `object_storage` 的 access key/secret key 是 sensitive；系统资源 bucket 和头像 bucket 由组合根选择，不允许业务端硬编码。
- 注册由组合根显式装配并 freeze；未知组、重复 key、不可序列化默认值启动失败。provider 选择值只由 settings 保存，具体 provider catalog 由组合根启动时注册。

### 4.6 site_cleanup

- 声明 `site.cleanup.retention.v1` Cron，并由 kernel `CronScheduler` 生成持久 task instance。
- 读取 `site_settings.operations.audit_retention_days`，清理超过策略期限的 audit entry、已投递/dead outbox、成功 inbox receipt 和终态 task instance。
- 清理由显式 activity 执行；audit capability 在同一 activity 中写入独立的 `audit.retention.cleaned` 摘要，不通过 GET、diagnostics 或 CLI 隐式修改记录。
- 不拥有 content 定时发布、points 桶过期、membership 到期或 OIDC signing key 清理的业务状态机；这些 capability-native handler 由组合根按 capability 装配。

### 4.7 membership_grants

- 只声明稳定的 `membership.grant` points behavior（`credit`、`credit` program、source type `membership`）。
- 不引入 payments、价格或订单，也不拥有会员表；管理平面通过 membership 的 PointsLedger Port 使用该行为授予当前周期额度。
- 该 feature 可随 `management_plane` 装配；支付购买流程仍由完整产品的显式 purchase feature 组装。

## 5. 示例流程的非需求声明

“待审入库 -> 通知管理员 -> 关键词过滤 -> 发布 -> 发放积分”只用于验证垂直工作流是否能在一处清晰表达，不自动成为 post 的产品行为。

如需启用，应建立单独 FeatureSpec，明确审核策略、关键词 provider、通知模板、积分行为和失败语义；不得通过全局事件订阅让这些行为隐式出现。

## 6. Feature 注册所有权

- content type 由 feature 注册，content capability 只验证和执行。
- content type 同时注册正文 format/profile 与 `ContentPublicationPolicy` 绑定；消费 feature 可调用 assets 等公开 Port 完成发布校验，content 不得反向导入兄弟 capability 或 feature。
- taxonomy dimension 可由 feature 注册，taxonomy capability 只维护维度和 term 数据。
- points behavior 由 feature 注册，points capability 只执行账本规则。
- membership level 由 feature 注册（`level_specs`），membership capability 只校验和执行订阅规则。
- RouterSpec、workflow 和 Cron 同样由 feature 声明、api manifest 选择。
- 同一稳定 key 只能有一个 owner；重复注册必须启动失败。
- 完整产品 manifest 不注册 `check_in`、`point_purchase`、`membership_purchase`、`content_engagement` 独立 feature；对应 workflow/behavior/handler 分别由 `user_center` 或 `post` 声明。

## 7. 验收

- `user_center`、post、page 只靠公开 Command/Query/Port 组装 capability，不复制或访问 ORM/Repository。
- page manifest 中不存在 taxonomy、engagement 或 comments 注册。
- `user_center` 中的 check-in 并发请求只产生一次有效奖励。
- `user_center` 中的 point purchase 在 webhook 重放、乱序、worker 重启时不重复入账。
- `user_center` 中的 membership purchase 在 webhook 重放时只开通一次订阅并只授予一次积分。
- post 未启用时没有用户 post/engagement/comments 路由或投影 handler；page 可独立启用。
- community 启用/禁用直接控制 discussions/tags 用户路由、管理员路由和搜索投影；它不注册 content type、taxonomy dimension 或 comments target。
- post/page 的 Markdown 发布校验只通过公开 Port 完成；任一 feature 未启用时不遗留 validator、renderer、路由或后台副作用。
- entitlements 组数值由业务 feature 读取后以固定金额调用 points，组本身不执行积分逻辑。
- 示例审核流程可作为合同测试 fixture 证明每步崩溃可恢复，但未加入生产 manifest 时无运行副作用。
