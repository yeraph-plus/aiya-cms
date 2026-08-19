# 用户站实施合同

> 状态：目标实施文档，不是当前完成度报告。开发阶段数据库以当前 metadata 重建 baseline，不承担历史开发数据兼容。

本文件把 [`user-site.md`](user-site.md) 和后端规格转换为唯一的落地顺序、替换边界与验收证据。它不维护日期、负责人、百分比或另一套产品需求；行为真相仍由对应 capability/feature 规格持有。

## 1. 实施原则

每个阶段都按以下顺序完成：

1. 同步对应规格和稳定 key。
2. 写出会失败的架构、合同、状态机或 HTTP 测试。
3. 实现最小公开 Command/Query/Activity/feature gateway。
4. 增加迁移、manifest、router、worker 和 adapter 组合。
5. 重新生成 OpenAPI 与消费端类型。
6. 执行阶段门和跨阶段回归。

禁止用兼容 feature、双写表或转发 router 长期保留旧架构。旧路径的删除与目标路径挂载属于同一个可回滚变更集。

## 2. 目标目录

```text
inc/
  capabilities/
    archive/
    membership/
    points/
    payments/
    gift_cards/
    content/
    taxonomy/
    comments/
    engagement/
    community/
  features/
    user_center/
    business_center/
    post/
    page/
    work/
  adapters/
    archive/openlist/
    archive/gofile/
  api/
    composition/
    routers/
site/
  src/
    pages/
    components/
    islands/
    lib/api/generated/
    lib/auth/
    lib/markdown/
    layouts/
```

目录只表达所有权，不授权 feature 访问 capability 内部包。feature 只导入各 capability 的公开 Command/Query/Activity/DTO。

## 3. 旧实现替换清单

| 当前零散项 | 目标所有者 | 处理 |
| --- | --- | --- |
| `check_in` feature、旧 `MeService` | `user_center` | 行为迁入 gateway 后删除声明、router、tests 中的旧 key |
| `membership_grants` feature | `user_center` + membership cycle protocol | 删除；不得让 membership 直接调用 points |
| `point_purchase` feature | `user_center` | 合并 offer/payment/fulfillment workflow |
| `membership_purchase` feature | `user_center` | 合并 payment -> cycle -> expiring credit -> activation |
| feature 外的 gift card -> points/membership 组合 | `user_center` | 统一预留、履约、核销与恢复 |
| `content_engagement` feature | `post`、`work` | 删除通用目标 router，目标类型由各 feature 固定 |
| page 无 taxonomy 的旧声明 | `page` | 改为只注册 `page.category` |
| content 只有 post/page 的旧 allowlist | `work` | 新增 work data/taxonomy/comments/engagement manifest |
| payments 不挂用户购买/callback 的旧 release | `user_center` + payments callback router | 购买入口在 user_center；provider 回调只进入 payments |
| 完整 OpenAPI 作为客户端合同 | admin/user projections | admin 管理 SPA 与 site 分别生成类型 |

删除前先以测试枚举所有旧稳定 key、路由、订阅和 worker；目标装配通过后断言旧项 404/未注册。不得保留同义别名。

## 4. 数据与迁移策略

- 当前仍处于开发阶段，`release_0001` 直接反映当前 SQLAlchemy metadata；结构变化通过清库后重建 baseline 验证，不为开发数据库增加兼容 revision、`ALTER` 或旧状态转换。
- 新表必须标注 capability owner；feature 的持久状态只使用 kernel workflow/task 表或明确归属 feature 的 workflow projection，不建立万能订单表。
- membership subscription 与 cycle facts 由 baseline 一次创建，不迁移旧 renewal/subscription 快照，也不伪造 points entry。
- content work 的 JSONB 必须绑定版本化 Pydantic schema；迁移不把 provider path/token/raw URL 写入 content。
- archive locator 必须加密/受限存储并支持 provider/version；grant 与 delivery attempt 不与 content/points 建外键。
- points 复用现有 program/ledger/bucket，只新增声明的 behavior key，不另建“下载余额”或“会员余额”。
- payments 复用自己的 order/attempt/webhook/refund 表；user_center 只保存 payment order opaque ref 与 fulfillment workflow state。
- 所有 migration downgrade/upgrade、空库 migrate、baseline metadata 一致性和 install 重放都要在隔离数据库验证。

## 5. 阶段 A：架构护栏先行

先增加失败测试：

- membership 导入 points/payments/gift_cards/identity 失败；
- user_center/business_center 导入 capability ORM/Repository/表失败；
- API handler 出现 Session、裸 SQL、价格计算、余额计算或 provider 选择失败；
- content JSONB 出现 provider locator/token/raw URL/header 字段失败；
- 旧 feature/router key 仍注册失败；
- provider catalog 缺少允许 key、出现自动发现或启动联网失败。

阶段完成证据是测试确实在旧实现上失败，并能精确指向边界，而不是只新增空包或 TODO。

## 6. 阶段 B：archive capability 与 adapters

实施顺序：

1. archive DTO、模型、Repository/UoW、Commands/Queries、grant 状态机和迁移。
2. `ArchiveDeliveryProvider` 合同与 fake adapter。
3. `archive.openlist`、`archive.gofile` HTTP SDK adapter。
4. settings schema、ProviderCatalog 全量注册与 runtime Resolver。
5. admin 普通管理 CRUD/命名状态端点和 admin OpenAPI。

必须先通过 capability 合同测试，再做 provider HTTP mock。真实 provider 连通性不是单元/CI 前提；启动时不探测网络。

## 7. 阶段 C：membership 原子边界纠偏

1. 写失败测试证明 membership 当前直接授予积分的实现不符合目标。
2. 实现 `PrepareSubscriptionCycle`、`AttachPointsGrant`、`MarkCycleFailed` 和 cycle Queries。
3. 在开发 baseline 中直接创建 subscription/cycle 当前结构。
4. 删除 `PointsLedgerPort` 及跨 capability 共享 UoW 方案。
5. 验证未 attach points entry 时不提供会员权益，重放 attach 不改绑。

此阶段只建立原子协议，不在 membership 内实现购买、礼品卡或 payments。

## 8. 阶段 D：user_center

按一个 feature、多个明确 workflow 实现：

- `/me` 资料与头像 upload/finalize；
- daily check-in；
- points balance/ledger projection；
- point product purchase；
- membership offer purchase/renew/cancel；
- gift card -> points；
- gift card -> membership；
- captured/refunded payment result fulfillment；
- membership cycle expiring points credit 与 crash recovery。

每条 workflow 都要有稳定 key、版本、恢复点、幂等键和人工诊断视图。测试覆盖每个提交边界后的 crash：payment captured、points credited、membership prepared、membership attached、gift card reserved/redeemed。

实现完成后删除 `check_in`、`membership_grants`、`point_purchase`、`membership_purchase` 的 manifest、router、worker 和兼容测试。

## 9. 阶段 E：三种内容类型

### post

- 注册 post content/data schema；
- 注册 `post.category`、`post.tag`；
- 组合 comments 与 engagement；
- 列表、详情、显式 view/like/rating/favorite。

### page

- 注册 page schema 与 `page.category`；
- 明确不注册 tag/comments/engagement；
- 未声明端点保持 404。

### work

- 注册 work schema和 namespace taxonomy；
- JSONB 保存 archive opaque file manifest snapshot；
- 组合 comments 与 engagement；
- 发布前校验 archive item active、manifest 固定且符合分卷 profile；
- 列表/详情不解析或返回 provider locator。

三种类型共享 content 原子能力，不复制 ORM/Service。删除 `content_engagement` 后，用 post/work 的 FeatureSpec 分别注册目标固定的 handler/router。

## 10. 阶段 F：business_center

1. 建立 `BusinessProductSpec`、PricingPort、FulfillmentPort、quote DTO 与 frozen registry。
2. 实现 `archive.files.fixed.v1`：`quantity=file_count`、`unit_price=100`、program=`credit`。
3. 实现 quote version/expiry 和服务端重算。
4. 实现 consumption 持久 workflow：debit points -> create archive grant -> complete。
5. 覆盖扣费后 crash、履约暂时失败、幂等重放、余额不足、manifest 漂移、grant 窗口内 link refresh。
6. 为未来 AI/OIDC 客户端保留显式 product 注册和 scope/subject/client 审计，不提供任意 amount debit API。

不得建立通用业务订单/购物车/商品 ORM。消费事实由 points ledger、目标 capability grant/fact 与 kernel workflow 共同闭合。

## 11. 阶段 G：API composition 与 OpenAPI

- release manifest 显式装配 archive、user_center、business_center、work 和全部允许 providers；
- API 只绑定 Port、授权依赖、router、worker 和 lifecycle；
- provider callback router 只把原始请求传入 payments 验签/处理；
- user router 使用 generated DTO、subject/client scope、Idempotency-Key 和稳定错误映射；
- 从同一个 frozen release schema 投影 admin/user；按 path allowlist、component reachability 和稳定排序验证；
- admin 覆盖全部 `/api/v1/admin/**`；user 保留 auth、`/me`、内容、社区、user_center、business_center；
- webhook/internal repair/provider secret 从两个客户端投影排除；
- 分别生成 admin/site TypeScript 类型，并删除手写 DTO。

`openapi.json` 只用于系统验证；若停止产出，必须先有等价测试证明完整 release schema 可构建且投影闭包没有遗漏。

## 12. 阶段 H：Astro SSR 用户站

建议顺序：

1. Node standalone、runtime env、generated user client、统一错误/request ID 处理。
2. Redis session 与 OIDC confidential code + PKCE。
3. 共享 Markdown、安全渲染、public cache/SEO primitives。
4. post/page/work 列表与详情。
5. community 最小页面。
6. account shell、资料、头像、points、membership、purchases、gift card。
7. quote/confirm/processing/download grants 与 link refresh。
8. 可访问性、no-JS 公开阅读、响应式和错误边界。

Vue island 只用于评论、互动、签到、表单、workflow polling 和下载链接刷新等局部交互。页面首次数据与授权由 Astro server 完成，不能在 hydration 后才决定是否泄露私有内容。

## 13. 测试矩阵

| 层 | 必须覆盖 |
| --- | --- |
| Architecture | import graph、表所有权、API purity、manifest allowlist、provider 注册 |
| Capability | points bucket/FIFO/expiration、membership cycle、payments webhook/refund、gift card reserve/redeem、archive grant |
| Feature | user_center 每条 workflow、business_center quote/debit/fulfillment、post/page/work 组合 |
| API | auth/RBAC/subject scope、idempotency、错误映射、admin/user projection |
| Adapter | PayPal/Epay/OpenList/Gofile HTTP mock、timeout/limit/signature/expiry/desensitization |
| Site unit | session、generated client、forms、renderer、state mapping、SEO |
| Browser E2E | OIDC、资料/头像、签到、购买/回调、兑换、积分下载、无权访问 |
| Release | clean migrate/install、Compose、direct/proxied health、SSR/static/cookie/callback |

读路径副作用、重复请求、并发版本冲突、workflow crash/restart 和 provider 重复 callback 必须是独立的负面测试，不由 happy-path 间接代替。

## 14. 完成定义

只有以下全部成立才可以删除“目标规格，尚未实现”标记：

- 旧零散 feature/router/worker/import 已删除，未知旧 key 启动失败或路由 404；
- 开发 baseline 在空库 upgrade/downgrade 及 metadata 一致性检查中通过，install 可重放；
- backend/admin/site 质量门与两个 OpenAPI 快照通过；
- payment、membership points grant、gift card 与下载 consumption 的 crash/retry 没有重复价值变化；
- OpenList/Gofile secrets、locator、headers、raw links 不出现在内容、日志、缓存或 schema；
- 生产 Compose 中 Astro SSR、admin 静态站和 API 直接/代理路径均验证；
- 交付报告把已实现、已验证、环境阻塞和后续范围分别列出。

部分完成时只能报告对应阶段证据，不能把“有代码”“有页面”“有 Compose”称为完整用户站交付。
