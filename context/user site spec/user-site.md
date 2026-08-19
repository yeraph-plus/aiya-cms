# 用户站规格

> 状态：下一用户站版本的目标合同，尚未实施。本轮只定义规格；落地顺序与替换清单见 [`IMPLEMENTATION.md`](IMPLEMENTATION.md)。

## 1. 产品范围

`site/` 是面向访客、注册用户和受授权 OIDC 客户端的 Astro SSR 用户站。它只消费 `openapi.user.json` 生成的客户端与本目录设计合同，不导入 Python 源码、管理员生成类型、数据库模型或 provider SDK。

首个完整用户站交付：

- 注册、邮箱验证、密码找回、登录、OIDC callback、登出；
- 普通文章 post、文档页面 page、作品文章 work；
- Flarum-like 最小社区；
- `/me` 资料、头像、签到、积分、会员、购买和礼品卡兑换；
- 作品文件的积分报价、消费、授权与下载入口；
- SSR SEO、可访问性、错误边界和生产部署。

不交付：通用电商商品平台、用户间转账、法币钱包、购物车、全站搜索平台、社区插件市场、E-Hentai 标签投票权重、浏览器直连 provider 管理 API，以及 AI 写作产品本身。

## 2. 系统边界

```text
Browser
  └─ host-only HttpOnly session cookie
         ↓
Astro SSR / BFF
  ├─ OIDC confidential client + PKCE
  ├─ Redis-backed server session
  ├─ generated openapi.user client
  └─ HTML / Vue islands
         ↓
FastAPI release API
  ├─ auth / user_center / business_center features
  ├─ content/community capabilities
  └─ API composition root
         ↓
points / payments / archive and provider adapters
```

Astro 负责页面组合、SSR、BFF 会话、表单体验和 SEO；FastAPI 是认证、授权、价格、余额、状态机和幂等性的最终边界。Vue island 只用于需要局部交互的区域，不能复制一套浏览器业务状态机。

## 3. 会话与认证

Astro 是 server-side confidential OIDC client，使用 Authorization Code + PKCE：

- client secret、access/refresh token、PKCE verifier、state、nonce 和服务端 session 均不进入浏览器 bundle、HTML、Vue props、URL 或本地存储；
- 浏览器只持有 `Secure`、`HttpOnly`、host-only、`SameSite=Lax` 的短标识 cookie；
- callback 先校验 state/nonce/verifier，再创建或轮换服务端 session；
- 登录前目标只能保存同源相对 URL，拒绝开放重定向；
- logout 撤销本地 session，并按 OIDC 合同处理上游登出；
- 所有敏感 POST 使用同源检查与 CSRF 防护；Idempotency-Key 不能替代 CSRF。

用户认证合同必须来自 user OpenAPI，并保留：

- `/api/v1/auth/register`
- `/api/v1/auth/verify-email`
- `/api/v1/auth/password-reset/*`
- `/api/v1/me`

匿名访问受保护页面时，SSR 返回登录引导或同源跳转；API 的 401/403 不伪装成空数据。callback、刷新和 cookie bootstrap 的竞态必须有浏览器测试。

## 4. 路由与页面所有权

| 页面 | 目标 | 认证 | 主要合同 |
| --- | --- | --- | --- |
| `/` | 编辑型首页 | 可匿名 | post/work/page 精选与社区摘要 |
| `/posts`、`/posts/[slug]` | 普通文章列表/详情 | 可匿名 | post + taxonomy + comments + engagement |
| `/pages/[slug]` | 文档页面 | 可匿名 | page + category |
| `/works`、`/works/[slug]` | 作品列表/详情 | 可匿名浏览 | work + namespace taxonomy + comments + engagement |
| `/community` | 社区首页与讨论列表 | 可匿名浏览 | community tags/search/order |
| `/community/d/[id]` | 讨论详情 | 可匿名浏览，写入需登录 | discussion/post/moderation |
| `/login`、`/auth/callback` | OIDC 会话 | 不适用 | Astro BFF |
| `/register`、`/verify-email`、`/password-reset/*` | 身份流程 | 匿名 | auth feature |
| `/account` | 用户中心总览 | 必须登录 | `/me`、points、membership |
| `/account/points` | 余额、到期桶、账本、签到 | 必须登录 | user_center |
| `/account/membership` | 等级、当前周期、购买/续费/取消 | 必须登录 | user_center + payment result |
| `/account/purchases` | 购买、兑换和履约状态 | 必须登录 | user_center |
| `/account/gift-card` | 卡密兑换 | 必须登录 | user_center |
| `/account/downloads` | 已授权下载与链接刷新 | 必须登录 | business_center + archive |

用户详情、订单或 workflow ID 不得通过可枚举页面暴露他人资源；服务端每次查询都绑定当前 subject/client。

## 5. 内容产品

### 5.1 普通文章 post

- taxonomy：一个 `post.category` 加多个 `post.tag`；
- 支持评论区、显式 view、like/favorite、rating 和计数摘要；
- GET 详情不隐式增加 view，进入可见正文后由 island 明确发送一次 view Command；
- 列表支持 category/tag、发布时间和允许的 engagement 排序；
- 详情 SSR 输出 title、excerpt、canonical、Open Graph 和安全 Markdown HTML。

### 5.2 文档页面 page

- taxonomy 只允许一个 `page.category`；
- 不显示 tag、评论区、view/like/rating 或下载购买；
- 用于稳定文档与说明，不实现父子页面树；
- 导航层级由站点配置/页面组合决定，不改变 content 模型。

### 5.3 作品文章 work

- namespace taxonomy：category、source、creator、group、character、language、genre、format；
- 支持评论区、显式 view、like/favorite、rating 和计数摘要；
- 详情展示可下载文件的公开逻辑清单、part 数、公开大小/checksum、价格规则和购买状态；
- content JSONB 只持有 archive item opaque ref 与 manifest version，不持有 OpenList/Gofile 路径、token、raw link 或 secret headers；
- namespace 只借鉴“同一标签词在不同语义空间中区分”的方式，不复制外站投票、weak/solid 或用户标签权重系统。

三种类型共享安全 Markdown renderer。Markdown 原文来自 API；SSR 与管理预览复用同一渲染包、sanitizer 配置和恶意 fixture。原始 HTML、脚本、危险 URL scheme 与不受信 iframe 默认拒绝。

## 6. 社区最小产品

community 是独立 capability，不映射为 content/comments/taxonomy：

- 社区首页：标签空间、最新活动和讨论入口；
- 讨论列表：`latest`、`newest`、`top`，以及领域内 relevance 搜索；
- 创建讨论、回复、编辑自己的内容；
- 管理员/版主锁定、隐藏、恢复和受审计审核；
- 确定性分页，状态和权限由后端裁决；
- 首版不实现私信、反应插件、徽章、复杂信任等级、实时在线状态或社区积分。

社区页面可以在首页显示只读摘要，但不与 post/work engagement、comments 或 taxonomy 共享表和事件 key。

## 7. 用户中心

user_center 是取得价值和账户聚合的唯一用户 feature。页面只调用其公开 HTTP 合同，不直接串联 points、membership、gift_cards 或 payments。

### 7.1 资料与头像

- `/account` 展示当前身份、资料、头像、会员周期和默认积分概览；
- 资料更新使用版本并发控制；
- 头像走 upload intent -> 客户端上传 -> finalize；浏览器不获得对象存储 credential；
- GET `/me` 不签到、不刷新余额、不写 view，也不触发任何奖励。

### 7.2 签到与积分

- 签到只能由显式按钮触发，日期边界和奖励由服务端 settings/feature 决定；
- 重复点击展示 `already_rewarded`，不能重复 credit；
- 积分页区分 available total、永久桶、按最早到期排序的 expiring bucket 与 ledger；
- 用户站首版只把 `credit` program 作为可消费币值。后端存在其他 points program 不代表前端可以混用或兑换。

### 7.3 积分购买

- 页面从服务端 offer catalog 读取 point product；客户端只提交 offer key 和幂等键；
- user_center 创建 CNY payment order，支付成功后才 credit points；
- pending、captured-but-fulfilling、fulfilled、failed、refunded 必须是可恢复的明确 UI 状态；
- 页面轮询或刷新读取订单状态，不把浏览器回跳当成支付成功事实。

### 7.4 会员购买与周期积分

- 页面展示等级、周期天数、价格和每周期赠送积分；
- payment captured 后，user_center 准备会员周期、创建 `expires_at = cycle end` 的积分桶，再激活会员；
- 在积分已入账而会员 attach 暂时失败时显示“处理中”，由持久 workflow 恢复，前端不得再次创建订单；
- 取消只停止自动续费，当前周期与积分到期时刻保持不变；
- 到期后剩余周期积分由 points expiration 清理，不显示为可用余额。

### 7.5 礼品卡兑换

- 卡密只在提交表单时出现；不得写入 URL、analytics、错误日志或浏览器持久存储；
- user_center 根据服务端 target snapshot 兑换 points 或 membership；客户端不能选择与卡定义不同的 target/value；
- 预留、履约、核销可恢复，重复提交返回同一结果；
- 卡密不可用、已兑换、过期与暂时处理中使用不同稳定错误/状态。

## 8. 支付边界

现实法币仅存在于 payments capability：订单、attempt、provider session、webhook receipt、capture、refund，以及未来可能的法币余额均由 payments 闭合。

- user_center 只提交受信 purpose/offer 和服务端价格；
- PayPal/Epay 回跳只用于用户体验，provider callback/webhook 验签事实才推进支付状态；
- 任何其他 capability/feature 不创建自己的法币 order 或 balance 表；
- 页面不能修改币种、金额、subject 或 fulfillment target；首版只接受 CNY；
- 退款先由 payments 形成受信结果，再由 user_center 按产品合同执行 points/membership 补偿，不能在 webhook router 中跨能力写库。

## 9. 业务中心与积分下载

business_center 是系统内消费的统一入口。它不拥有业务资产，只关心“哪个受信产品、哪个目标、需要多少 `credit`、成功后如何履约”。

### 9.1 报价

首个产品 `archive.files.fixed.v1`：

- 一个 work 的可购买目标是发布时冻结的完整文件 manifest；
- `price = file_count × 100 credit`；
- 上传约定为 4 GiB 分卷：非最后一卷必须等于 4 GiB，最后一卷不大于 4 GiB；
- 计费按 manifest 文件数，不按实时 provider 报告的 byte 数动态变化；
- quote 包含 product key、target ref、manifest version、unit price、quantity、total、currency program 和短时过期时间；
- 执行时服务端重新计算或校验 quote version，客户端数字只用于展示。

### 9.2 消费与履约

```text
work published manifest
   ↓ quote
business_center trusted pricing
   ↓ debit 100 × file_count from points.credit
archive create/return delivery grant
   ↓
browser-safe download links or same-origin proxy
```

- 同一 consumption Idempotency-Key 只能产生一次 debit 和一次业务履约；
- 积分不足在扣费前失败；扣费成功但 archive 暂时失败时进入可恢复状态，不能再次扣费；
- grant 在授权窗口内刷新链接不重复扣费；窗口过期后的再次消费按新合同处理；
- provider URL、认证 headers 和 token 不进入 SSR cache、analytics、referer、SEO 或持久页面 props；
- 优先使用 same-origin redirect/proxy 或后端认定 browser-safe 的短时 URL；
- 页面应在消费确认前显示文件数、固定单价、总价、余额与不可逆/有效期说明。

未来 AI 写作或 OIDC 绑定客户端通过注册自己的 product/pricing/fulfillment 合同复用 business_center；它们不能向 `DebitPoints` 直接提交任意 amount，也不能复用 archive 的业务表。

## 10. 数据获取、缓存与一致性

- SSR 只缓存匿名、公开、无用户差异的 GET；包含 session、余额、订单、grant、下载 link 的响应一律 private/no-store。
- API Query 保持读路径纯净；页面渲染不能触发签到、view、续费、link 刷新或 provider probe。
- post/page/work 发布内容可使用 surrogate key 或版本化 revalidation；权限变化和下架必须能主动失效。
- community 列表与 engagement 摘要允许短暂最终一致，UI 不承诺强实时计数。
- payment、points debit 与 workflow 状态不做乐观成功；UI 以服务端终态为准。
- 浏览器 abort 不等于取消后端 workflow；恢复页面必须能通过 workflow/order ID 查询同一 subject 的状态。

## 11. SEO 与分享

- post/page/work 详情 SSR 输出唯一 canonical、title、description、Open Graph 和结构化数据；draft/private/unpublished 不得进入 sitemap。
- taxonomy 与社区列表仅对有稳定公共价值的 canonical filter 建索引；组合筛选、排序、分页和搜索默认 `noindex,follow`。
- account、auth callback、购买、订单、下载和错误页面全部 `noindex,nofollow`。
- sitemap 只包含已发布、公开、可匿名访问的 URL，并使用内容更新时间。
- 下载 link、session identifier、quote/order/workflow/grant ID 不进入 canonical、Open Graph 或 analytics page URL。

## 12. 可访问性与交互

- SSR 首屏在 JavaScript 失败时仍能阅读公开正文、taxonomy 和价格说明；写操作可依赖增强脚本，但必须有可理解 fallback。
- 所有输入有可见 label、说明和字段级错误；错误不能只靠颜色。
- modal/drawer 管理焦点、Escape 和 focus return；支付跳转与不可逆积分消费需要明确确认。
- touch target、对比度、键盘顺序和 reduced motion 遵循 `DESIGN.md`。
- loading 不隐藏既有数据；pending workflow 使用状态说明而不是无限 spinner。

## 13. 错误与观测

用户站保留后端稳定 `code`、原始 `message` 和 request ID；本地化标题/行动建议不能覆盖后端 message。

错误至少区分：

- unauthenticated / forbidden；
- validation / optimistic conflict / idempotency conflict；
- insufficient points / quote stale；
- payment pending / failed / refunded；
- gift card unavailable / already redeemed / processing；
- archive unavailable / grant expired / link refresh failed；
- workflow processing / manual review required。

日志与 telemetry 允许 route template、status、稳定 code、request ID、duration 和脱敏 workflow state；禁止卡密、token、cookie、provider locator、download URL、secret headers、支付签名和完整用户输入。前后端通过 request ID 关联诊断。

## 14. OpenAPI 与类型

- site 只从 `openapi.user.json` 生成客户端；生成目录只读，不手改 DTO。
- user 投影包含公开内容、社区、认证、`/me`、user_center 和 business_center；不含 `/api/v1/admin/**`、payment webhook、provider DTO 或内部 repair Command。
- API base URL、OIDC issuer/client 和公共站点 origin 由运行时环境提供，不硬编码到镜像。
- schema 改变必须先更新后端规格与失败快照测试，再生成类型并修复消费端。
- BFF 可以包装 cookie/session transport，但不能改变状态码、错误 code、幂等键或价格字段语义。

## 15. 生产部署

- Astro 使用 Node standalone SSR 生产输出；不得运行 Vite dev server 或 `vite preview`。
- FastAPI、Astro、管理员静态 Nginx 与 infra 拓扑由 Compose 明确；容器镜像保持通用，issuer、origin、Redis、API URL 与 provider 设置通过 Compose `environment`/`env_file` 注入。
- session Redis 失败时受保护页面 fail closed；不能退化为浏览器 token 或进程内生产 session。
- health 区分进程存活与依赖 readiness，不通过 health 隐式调用外部支付/archive provider。
- TLS 终止、forwarded header 信任和 cookie secure 策略必须匹配部署拓扑。

## 16. 发布验收

目标用户站只有在以下证据同时成立后才算交付：

- architecture/import guards、迁移升级与空库 install 幂等通过；
- admin/user OpenAPI 投影、component pruning、生成类型和快照漂移门通过；
- backend capability/feature/API tests 通过，包括 workflow crash/retry/idempotency；
- site lint、typecheck、unit、SSR build 与无 JavaScript 公开阅读测试通过；
- 真实 Redis + 测试 OIDC 的登录/callback/logout/session expiry E2E 通过；
- payment mock 覆盖 captured/refunded/重复 webhook 与浏览器回跳不可信；
- OpenList/Gofile HTTP mock 覆盖交付、限流、过期、权限和脱敏；
- 作品报价、积分不足、一次扣费、履约恢复、窗口内刷新不重复扣费 E2E 通过；
- 直接与 Nginx/入口代理后的 health、SSR、静态资源、cookie 与 callback 均验证；
- admin 管理面既有 release gate 无回归。

只有文档、页面文件、构建成功或 Compose 配置都不是发布完成证据。
