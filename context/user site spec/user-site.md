# 用户站基础框架规格

本目录将用户站的运行合同、页面布局和视觉元素与后端规格分开组织：本文件定义 Astro/FastAPI 边界、认证、SEO、Markdown、端点与发布门；页面结构见 [`LAYOUT.md`](LAYOUT.md)，视觉语言、Design Tokens 与组件元素见 [`DESIGN.md`](DESIGN.md)。三者共同构成用户站设计案，但不得改变 `context/spec/` 中 capability、feature、HTTP 和安全边界的所有权。

## 1. 定位与本轮边界

`site/` 是面向普通访客和已登录用户的 Astro SSR 应用。它与 `admin/` 独立构建、独立部署，只通过 FastAPI 的 HTTP/OpenAPI 契约使用系统能力，不读取 Python 源码、数据库、migration、capability registry 或管理员前端代码。

本文件只冻结基础框架、认证会话、部署边界、feature 收敛方式和用户侧端点；页面布局、视觉语言、组件外观、响应式和具体设计元素分别由同目录 `LAYOUT.md`、`DESIGN.md` 冻结。设计文档不得覆盖本文件的认证、安全、SEO、可访问性、SSR 和 OpenAPI 合同。当前实现尚未满足本规格时，后续必须按“失败合同测试 -> 实现 -> 集成验证”推进，不保留旧用户路由兼容层。

## 2. 产品 Feature 收敛

完整产品 manifest 的用户业务组装收敛为三个稳定 feature：

| Feature | 组装职责 | 不得吸收的所有权 |
| --- | --- | --- |
| `user_center` | 当前用户资料与头像编排、签到、积分摘要/流水、积分购买、会员目录/订阅/购买、本人购买记录 | identity、assets、points、payments、membership 的表、Repository、ORM 和状态机 |
| `post` | `post` content type、category/tag、公开文章查询、engagement 投影及互动、post 评论目标策略与用户评论路由 | content、taxonomy、engagement、comments 的表和通用 Command/Query |
| `page` | `page` content type 与独立公开只读路由 | taxonomy、engagement、comments、路由树或父子页面模型 |

此外完整产品显式启用 `community` capability。它不是第四个跨能力 feature，而是直接拥有 discussion/post/tag/search 表、状态机、Command/Query 和 RouterSpec 的独立产品边界；Astro 只消费其 HTTP DTO。社区边界详见 [`community capability`](../spec/capabilities/community.md)。

`site_settings` 与 `site_cleanup` 继续作为站点/运维 feature，不算用户产品组装。原 `check_in`、`point_purchase`、`membership_purchase`、`content_engagement` 不再作为生产 manifest 中可独立启用的 feature；其业务声明迁入上述 owner 后删除旧 feature package，不建立转发 package 或重复注册。

既有 workflow/behavior key 的业务语义保持：`checkin.reward.v1`、`pointpurchase.purchase.v1`、`pointpurchase.refund.v1`、`membershippurchase.purchase.v1`、`daily_check_in.reward`、`purchase.completed.credit`、`membership.grant`。移动 Python 包不是协议改名理由；若行为语义变化，必须新增版本 key。

comments、engagement、membership、points、community 等仍是独立 capability。所谓“整合进 post/user_center”只表示由 feature 选择公开命令、查询、Port 绑定、投影 handler、RouterSpec 和 DTO，不允许 capability 反向依赖 feature，也不允许 feature 直接访问 capability 持久化实现。community 不参与该收敛，也不复用 post 的 content/taxonomy/comments 组合。

## 3. 前端技术组合

基础组合固定为：

- Astro SSR，Node standalone adapter；生产不是静态导出，也不运行开发服务器或 preview。
- Vue 3 islands + TypeScript strict。Astro 负责文件路由、SSR、middleware、session 和 server actions；Vue 只承载确实需要浏览器状态的交互块。
- Tailwind CSS 4 通过官方 Vite plugin 消费 `DESIGN.md` tokens；不使用已弃用的 `@astrojs/tailwind`。公开站点不复用管理员端 PrimeVue 主题。
- Reka UI 作为 Vue island 的无样式、可访问交互原语；Lucide Vue Next 提供可替换图标。Astro 静态组件优先使用原生语义 HTML，只有菜单、弹层等确有焦点/键盘状态的控件才使用 Reka UI 并 hydration。
- `openid-client` 负责 OIDC Discovery、Authorization Code、PKCE S256、state/nonce、token refresh、revocation 和 logout 协议处理，不手写 OAuth/OIDC 协议。
- Astro server session 使用 Redis driver；浏览器只保存不可猜测的 host-only session ID cookie，token 和 client secret 只存在服务端 session/环境配置。
- 用户 API 类型从 `openapi.user.json` 生成，基础请求层使用 `openapi-typescript` 生成的 path/schema 与 `openapi-fetch` server adapter；禁止手写重复 DTO、从管理员 adapter 导入类型或以 `any`/`unknown` 绕过契约。
- 包管理和脚本约定与 `admin/` 一致使用 npm，但两个应用保持可独立安装、测试、构建和发布。

选择 Vue 而不是 React 的理由是复用本仓库既有 Vue 3/TypeScript 维护经验，同时保留 Astro 的 HTML-first 模型；这不意味着共享管理员页面、store 或运行时代码。

首版不引入 Vue Router、Pinia、全站 SPA 壳或客户端全局请求缓存。跨页状态来自 Astro session 和服务端 API；Vue island 只接收可序列化的最小初始 props，并按 `client:load`、`client:idle` 或 `client:visible` 显式选择 hydration。

### 3.1 基础路由、国际化与主题

- 路由以 Astro 文件路由和集中式 route manifest 为准；middleware 只执行显式 `public`、`anonymous-only`、`authenticated` 策略，未知路径不靠前端 catch-all 冒充业务页面。受保护页面未登录时跳转 BFF login，并只接受当前站点内的安全 return path。
- 首版语言为 `zh-CN` 与 `en`，默认 `zh-CN` 不加前缀，英文使用 `/en/**`。Astro 持有文件路由和 locale 解析；翻译采用共享的类型化 message catalog，Vue island 只接收当前控件所需的最小文案，不为此引入 Vue Router 或全局 SPA i18n store。
- route manifest 同时生成主导航与 locale path；切换语言保留受支持的同名页面，不存在的目标回到该语言首页。OIDC transaction 保存发起语言，callback 后恢复该语言的安全 return path。
- 主题值只允许 `system|light|dark`。`system` 使用 `prefers-color-scheme`；显式主题只保存非敏感的 host-only preference cookie，并以 `<html data-theme>` 和 CSS tokens 生效。主题控制不得持有 session/token，也不得造成核心内容依赖 JavaScript 才可阅读。
- 基础 AppShell、skip link、焦点样式、键盘导航、44px 触控目标、错误/离线状态必须可用；颜色与组件状态同时满足 `DESIGN.md`，不能只靠颜色表达状态。

## 4. 认证、会话与请求路径

生产基线使用不同二级域名，例如：

- 用户站：`https://www.example.com`；
- FastAPI/OIDC issuer：`https://api.example.com`。

用户站登记为 first-party **confidential** OIDC client。Astro BFF 使用 Code + PKCE S256；client secret、authorization code verifier、access token 和 refresh token 不下发到 Vue island，不写入 localStorage/sessionStorage/indexedDB，也不进入 HTML、日志或错误页。

请求路径固定为：

1. 浏览器访问 Astro；Astro middleware 从 server session 建立用户上下文。
2. 登录跳转到 FastAPI issuer；callback 回到用户站 origin，由 Astro server 完成 code exchange 并轮换 session ID。
3. SSR 读取和 server action 写入均由 Astro server 以 Bearer token 调 FastAPI；FastAPI 不接受 Astro session cookie。
4. Vue island 的状态写入调用同源 Astro action/endpoint，由 BFF 透传 request ID、Bearer 和所需 `Idempotency-Key`。
5. 头像二进制继续使用受限 upload intent 直传 object storage；支付使用受信 checkout URL 跳转。Bearer、refresh token 和 client secret 不发送给 storage/payment provider。

Astro session cookie 必须为 `Secure`、`HttpOnly`、host-only、`SameSite=Lax`，并在登录、权限提升和登出时轮换或销毁。所有同源状态写 action 校验 Origin/Host 并使用 CSRF token；session 数据有绝对期限和空闲期限，Redis 不可用时认证请求 fail closed，匿名公开页面可以继续服务。

FastAPI 生产 CORS 保留精确用户站/管理员站 origin allowlist，禁止 `*`。用户站基线不直接从浏览器 fetch FastAPI，因此不启用 credentialed CORS；未来若某个 endpoint 需要浏览器直连，必须逐端点补充 token、CSRF/CORS、cache 和错误合同，不能仅扩大全局 allowlist。

## 5. SEO 文档与 Head 所有权

用户站前端拥有最终公开 URL 和 SEO 输出契约。FastAPI 只提供经过校验的结构化站点默认值、内容事实和编辑覆盖值；不得生成 `sitemap.xml`、`robots.txt`、页面 HTML、`<head>` 标签或 JSON-LD 字符串。

标准爬虫文件名固定为 `robots.txt`；不生成 `robot.txt` 兼容路径。Astro 必须在用户站 origin 直接提供：

- `GET /robots.txt`：`text/plain; charset=utf-8`；
- `GET /sitemap.xml`：`application/xml; charset=utf-8`；超过单文件协议上限时返回 sitemap index，并生成确定性分片；
- 每个可索引 SSR 页面在首个 HTML 响应中生成完整 `<head>`，不依赖 Vue hydration 或客户端二次修改。

### 5.1 SEO 输入与所有权

- Astro 部署配置中的用户站 origin 是 canonical URL 的最终权威；`site_settings.seo.canonical_host` 是发布期预期值，二者不一致必须在启动/发布检查中 fail fast。API origin 不得出现在页面 canonical、sitemap 或 `og:url`。
- `GET /api/v1/site` 返回类型化 `seo` 投影，至少包含 site name、title template、default description、default share image asset reference、robots policy 和 expected canonical host；不返回预拼装标签、XML、任意 HTML 或 raw robots 文本。
- post/page feature 的 Pydantic `data` schema 可以声明类型化编辑字段 `seo_title`、`seo_description`、`seo_share_image_asset_id` 和 `seo_indexing`。它们只是内容事实/覆盖值；最终 URL、标签、robots 指令和结构化数据仍由 Astro 生成。
- 最终值优先级固定为“内容显式覆盖 -> site SEO 默认值 -> title/excerpt 等确定性内容 fallback”。空字符串视为未覆盖；同一页面不得生成重复 title、description 或 canonical。
- `seo_indexing` 使用受控枚举，不接受任意 meta/robots 字符串。draft、pending、scheduled、archived、认证页、用户中心页、callback、错误页和 preview 无论编辑值如何都不得进入 sitemap，并默认 `noindex, nofollow`。

### 5.2 Head 输出

可索引 post/page 的 SSR `<head>` 至少生成：

- `<title>`、meta description、唯一 absolute canonical；
- robots meta；
- Open Graph 的 `og:title`、`og:description`、`og:type`、`og:url` 和可用时的 `og:image`；
- Twitter card 的 title、description 和可用时的 image；
- Astro 根据结构化 DTO 生成并安全序列化的 JSON-LD：站点级 `WebSite`，post 使用 `Article`/`BlogPosting`，page 使用 `WebPage`；后端不得下发可直接执行或原样注入的 JSON-LD/HTML。

canonical 默认移除 tracking/query/hash；确需可索引分页时由对应页面路由显式定义分页 canonical，不由通用 helper 猜测。内容 API 返回的 slug、published/updated time、author public projection 和 asset reference 是生成元数据的事实输入。

SEO share image 必须是爬虫可访问的稳定 absolute URL。settings/content 继续只保存 opaque asset ID；短期 provider signed URL 禁止直接进入 `<head>`。Astro 以用户站 origin 暴露稳定媒体地址（如 `/media/assets/{asset_id}`），服务端再解析/代理当前 provider 对象，并以 asset version/content hash 管理缓存失效。

### 5.3 Sitemap 与 Robots

- sitemap 只包含当前 manifest 中 published 且允许索引的 post/page canonical URL；不包含 API、管理员端、认证/用户中心、preview、query 变体、草稿、待审、定时未发布或归档内容。
- `lastmod` 只来自内容的可信 `updated_at`/`published_at`，不得使用 sitemap 请求时刻伪造变化。URL 顺序必须确定，分片边界稳定。
- `robots.txt` 由 Astro 把类型化 robots policy 映射为文本，并始终输出用户站 absolute sitemap URL。生产环境按已发布策略生成；非生产/preview 环境强制 `User-agent: *` + `Disallow: /`，不能由数据库设置放开索引。
- `/robots.txt`、`/sitemap.xml` 和匿名 head 数据可以使用 public cache/ETag，但 settings/content 版本变化后必须失效；生成失败时不得返回陈旧但状态为成功的空 sitemap。
- sitemap 生成可以分页读取既有 post/page 公开 Query；若规模使请求时聚合不可接受，再新增只读、cursor 化的 `site indexables` DTO。该 DTO 只提供结构化 URL 事实，不把 XML 所有权移回 FastAPI。

## 6. Markdown 内容与渲染合同

`contents.body` 中规范化后的 Markdown 原文是唯一正文事实源。FastAPI 负责按 [`content capability`](../spec/capabilities/content.md) 校验并保存 `gfm-v1`，不得在数据库、事件或用户 DTO 中保存/返回 `rendered_html`；Astro SSR 负责把服务端返回的原文安全渲染为最终页面 HTML。

### 6.1 API 传输合同

- `PostDetailDTO`、`PageDetailDTO` 和有权限的内容编辑 DTO 返回 `body`、服务端派生的 `body_format="markdown"`、`body_profile="gfm-v1"` 及内容 `version`；create/update request 只接收 `body`，不得提交 format/profile。
- 正文上限为规范化后 524288 UTF-8 bytes。OpenAPI description 和稳定错误 code 必须明确 byte 语义；不得误用 JSON Schema `maxLength` 表达 byte 上限。
- 用户公开 DTO 返回原文而非 HTML；Astro server 在 SSR 边界渲染。Vue island 不直接接收未经必要性证明的完整正文或可注入 HTML。
- `excerpt` 是卡片摘要和 SEO description 的确定性 fallback；不从 Markdown 在每次请求时临时截断生成摘要，也不保留 `PostData.summary` 的第二来源。

### 6.2 共享渲染内核

仓库提供无 Astro/Vue 依赖的纯 TypeScript `packages/markdown`。Astro SSR 和管理员预览必须使用同一版本、同一 profile 与同一测试语料；不得各自实现一套 Markdown 方言。

`gfm-v1` 渲染管线固定为：

1. remark 解析 Markdown 并启用已登记的 GFM 语法；检测到 raw HTML/MDX/directive 节点即拒绝，mdast -> hast 保持 `allowDangerousHtml=false` 且不启用 `rehype-raw`；
2. 只执行登记的 mdast/hast 纯转换，包括安全 heading ID、链接属性和 `asset:<uuid>` 节点解析；
3. 在最后一个可能产生不可信 hast 的转换之后执行 `rehype-sanitize` allowlist；清洗之后只允许受信 stringify，不再运行会注入任意节点/属性的插件；
4. 返回只能在 server/preview 渲染边界消费的内部 `TrustedHtml` 类型；该类型不得成为 OpenAPI DTO、持久化字段或跨进程消息。

所有 Markdown 均视为不可信输入，即使作者是管理员。代码块只显示，不执行、`eval` 或加载任意运行时；首版不启用 diagram、iframe、任意 embed 或会执行内容的高亮插件。外部链接不得携带凭据，渲染时至少添加 `rel="noopener noreferrer"`；不强制依赖 `target="_blank"`。heading ID 使用确定性算法和固定安全前缀，不能覆盖页面已有 DOM ID。

`asset:<uuid>` 只在 Astro server 映射为用户站稳定路径 `/media/assets/{asset_id}`；provider object URL、短期 signed URL 和 API origin 不进入正文 HTML。渲染阶段不抓取远程链接或图片。

### 6.3 缓存、预览与版本

- 渲染缓存 key 至少包含 content ID、content version、body profile 和 renderer version；profile、sanitize allowlist、heading/link/asset 转换语义变化时必须增加 renderer version 并使旧缓存失效。
- 管理员编辑器保存 Markdown 原文，预览调用相同 `packages/markdown`；禁止把未经清洗的结果交给 `innerHTML`/`v-html`，也不向 FastAPI 请求预渲染 HTML。
- preview 页面始终 `noindex, nofollow`，不得进入 shared cache、sitemap 或公开 canonical。
- 搜索纯文本、目录和阅读时长等未来派生值必须可由原文 + profile 重建；不得反向覆盖 Markdown 原文。

当前 `Text` 列足以保存 Markdown，因此本合同本身不要求数据库 migration。项目尚未发布时直接把 post/page 目标 schema 收敛到上述基线，不增加 HTML 或 `summary` 兼容层；发布后 profile/schema 变化才按版本化迁移合同处理。

## 7. FastAPI 用户侧端点计划

以下是完整产品 manifest 的目标用户 HTTP 面。所有写入都调用 feature/capability 的公开 Command 或 workflow gateway；GET/HEAD 不写库、不发事件、不计数。

### 7.1 站点与认证公共面

| 方法与路径 | 认证 | Owner | 基础语义 |
| --- | --- | --- | --- |
| `GET /api/v1/site` | 匿名 | `site_settings` | 只返回 allowlist 内的 public settings、类型化 SEO 输入、当前公开 feature 摘要和缓存版本；不返回最终 head/XML/text、私有值、sensitive metadata 或管理员配置 schema |
| `POST /api/v1/auth/register` | 匿名 | identity/auth | 自助注册并触发带外邮箱验证 |
| `POST /api/v1/auth/verify-email` | 匿名 | identity/auth | 消费一次性邮箱验证 token |
| `POST /api/v1/auth/password-reset/request` | 匿名 | identity/auth | 等价响应，防止用户枚举 |
| `POST /api/v1/auth/password-reset/confirm` | 匿名 | identity/auth | 消费一次性 token 并设置新密码 |

OIDC authorize/token/UserInfo/revocation/logout、Discovery 和 JWKS 继续使用 issuer 标准端点，不复制到 `/api/v1/auth/**`。浏览器登录/callback/logout 路由属于 Astro BFF，不属于 FastAPI 业务 OpenAPI。

### 7.2 `user_center`

| 方法与路径 | 认证/幂等 | 基础语义 |
| --- | --- | --- |
| `GET /api/v1/me` | 登录 | 当前 subject 的最小身份、头像、默认积分摘要和当前会员摘要；缺失账户/订阅返回稳定空值且不写库 |
| `PATCH /api/v1/me` | 登录 + version/ETag | 只允许修改本人公开 profile 字段 |
| `POST /api/v1/me/avatar/upload-intents` | 登录 + `Idempotency-Key` | 创建头像 bucket 的受限上传意图 |
| `POST /api/v1/me/avatar/upload-intents/{intent_id}/finalize` | 登录 + `Idempotency-Key` | 完成 assets + identity workflow |
| `POST /api/v1/me/check-ins` | 登录；服务端业务日幂等 | 显式签到，返回本次状态、业务日期和余额 |
| `GET /api/v1/me/points` | 登录 | 默认 `credit` program 的余额与安全桶摘要；未开户为逻辑零值 |
| `GET /api/v1/me/points/ledger` | 登录 | 本人积分流水稳定分页 |
| `GET /api/v1/me/points/offers` | 登录 | 服务端受信积分商品目录 |
| `POST /api/v1/me/points/orders` | 登录 + `Idempotency-Key` | 启动 point purchase workflow，返回公开 order reference 与 checkout URL |
| `GET /api/v1/me/membership` | 登录 | 当前订阅、周期和授予快照；无订阅返回稳定空值 |
| `GET /api/v1/me/membership/offers` | 登录 | 服务端受信会员目录/价格快照 |
| `POST /api/v1/me/membership/orders` | 登录 + `Idempotency-Key` | 启动 membership purchase workflow |
| `GET /api/v1/me/purchases` | 登录 | 本人购买记录稳定分页，不返回 provider payload |
| `GET /api/v1/me/purchases/{order_reference}` | 登录 | 按公开 reference 查询本人 order/attempt/refund 安全摘要 |
| `GET /api/v1/me/favorites/posts` | 登录 | 本人已点赞 post 稳定分页 |
| `GET /api/v1/auth/grants` | 登录 | 本人未撤销 OIDC consent |
| `DELETE /api/v1/auth/grants/{client_id}` | 登录，幂等 | 撤销本人授权并失效相关 session/refresh family |

客户端不得提交 `subject_id`、金额、币种、积分数量、会员周期或授予额度。购买详情通过当前 Principal 限定 owner；未知和他人 order 对外均不得泄露存在性。

### 7.3 `post`

| 方法与路径 | 认证/幂等 | 基础语义 |
| --- | --- | --- |
| `GET /api/v1/posts` | 匿名；可选 Bearer | published post 分页；category/tag/filter/sort 使用 allowlist，返回卡片 DTO、公开 taxonomy、engagement 摘要和生成 sitemap/head 所需的结构化事实 |
| `GET /api/v1/posts/by-slug/{slug}` | 匿名；可选 Bearer | published post 详情；返回稳定 `post_id`、内容、taxonomy、engagement、SEO 编辑覆盖值和可选 viewer state |
| `POST /api/v1/posts/{post_id}/views` | 匿名；可选 `Idempotency-Key` | 唯一显式浏览计数入口；GET 详情不计数 |
| `PUT /api/v1/posts/{post_id}/like` | 登录，幂等 | 激活本人点赞 |
| `DELETE /api/v1/posts/{post_id}/like` | 登录，幂等 | 撤销本人点赞 |
| `PUT /api/v1/posts/{post_id}/rating` | 登录，幂等 | 设置本人 1-5 整数评分 |
| `DELETE /api/v1/posts/{post_id}/rating` | 登录，幂等 | 撤销本人评分 |
| `GET /api/v1/posts/{post_id}/comments` | 匿名 | 只返回 published 评论，稳定分页 |
| `POST /api/v1/posts/{post_id}/comments` | 登录 + `Idempotency-Key` | 提交纯文本评论或一层回复，初始为 pending |

Astro 的公开文章 URL 固定为 `GET /posts/{slug}`；`slug` 是创建时自动生成且不可变的 `generated_title_suffix_v1` 值。SSR 通过 `GET /api/v1/posts/by-slug/{slug}` 读取详情，随后只使用返回的 `post_id` 调用 views/like/rating/comments 等动作端点。浏览器地址、canonical、sitemap 和分享 URL 均使用 slug，不使用 UUID、数值 ID 或可逆短码。未知 slug 和非 published 内容对匿名请求均返回 404。

公开 post RouterSpec 由 `post` feature 拥有。它通过 content/taxonomy/engagement/comments 的公开 Query/Command 组成 DTO，不直接 join 兄弟 capability 表；需要高效批量读取时扩展 capability 公共批量 Query 或专用 readmodel Port，禁止在 API/router 中跨表拼接。

### 7.4 `page`

| 方法与路径 | 认证 | 基础语义 |
| --- | --- | --- |
| `GET /api/v1/pages` | 匿名 | published page 的最小目录和 sitemap 事实，稳定分页 |
| `GET /api/v1/pages/by-slug/{slug}` | 匿名 | published page 详情及 SEO 编辑覆盖值 |

page DTO 不包含 taxonomy、engagement、comments 或父子路由树。未来给 page 增加任一行为都必须更新 `page` feature，而不是复用 post 路由时临时放开 `type_name`。

### 7.5 `community`

| 方法与路径 | 认证/幂等 | 基础语义 |
| --- | --- | --- |
| `GET /api/v1/community/discussions` | 匿名；可选 Bearer | published discussion 分页；支持纯文本 `q`、单 community tag 和 `latest|top|newest`，搜索默认 relevance |
| `POST /api/v1/community/discussions` | 登录 + `Idempotency-Key` | 原子创建 discussion 与首帖，状态由 template/权限决定 |
| `GET /api/v1/community/discussions/by-slug/{slug}` | 匿名；可选 Bearer | published discussion 详情及首帖摘要 |
| `PATCH /api/v1/community/discussions/{discussion_id}` | 登录 + version | 编辑允许字段，不接受通用 status/locked PATCH |
| `GET /api/v1/community/discussions/{discussion_id}/posts` | 匿名；可选 Bearer | published post stream，按不可变 number 稳定分页 |
| `POST /api/v1/community/discussions/{discussion_id}/replies` | 登录 + `Idempotency-Key` | 创建 reply，遵守 lock 与审核策略 |
| `PATCH /api/v1/community/posts/{post_id}` | 登录 + version | 编辑本人或有权限的 post |
| `GET /api/v1/community/tags` | 匿名 | primary/secondary Tags 分区、层级与 published discussion count |
| `GET /api/v1/community/tags/by-slug/{slug}` | 匿名 | tag 详情与公开展示元数据 |

Astro 公开页面为 `/community`、`/community/discussions/{slug}`、`/community/tags`、`/community/tags/{slug}`。community 页面使用生成 DTO 和同一安全 Markdown renderer，但不导入 post/page adapter 或拼接 community 数据库查询。首版 community 页面固定 `noindex, follow`、不进入 post/page sitemap，浏览 URL 与 self canonical 仍使用不可变 slug；需要讨论或 tag 进入搜索引擎索引时先补充 indexability、分页 canonical、删除和 sitemap 语义。

### 7.6 不进入目标产品用户面的旧路由

下列当前路由在收敛实现完成时从完整产品 manifest 和 OpenAPI 删除，不提供 alias、redirect 或兼容 handler：

- `/api/v1/check-in`；
- `/api/v1/point-purchase/**`；
- `/api/v1/membership-purchase/**`；
- `/api/v1/content/{type_name}/**` 用户路由；
- `/api/v1/content/{target_type}/{target_id}/comments`；
- `/api/v1/me/favorites/{type_name}`。

管理员 `/api/v1/admin/**`、支付 webhook 和 capability 内部 Command/Query 不因用户路由收敛而改所有权。

## 8. DTO、缓存与错误

- 用户站主要组合 DTO 为 `SiteDTO`、`SiteSeoDTO`、`ContentSeoInputDTO`、`MeDTO`、`PointsSummaryDTO`、`MembershipSummaryDTO`、`PurchaseDTO`、`PostCardDTO`、`PostDetailDTO`、`PageDetailDTO`、`EngagementSummaryDTO`、`CommentDTO/Page`、`CommunityDiscussionCardDTO`、`CommunityDiscussionDetailDTO`、`CommunityPostDTO/Page` 和 `CommunityTagDTO`；它们是 Pydantic 边界 DTO，不暴露 ORM、派生 HTML、最终 SEO XML/text、搜索内部 rank/document 或 provider payload。详情 DTO 中的 `body` 是 Markdown 原文并带服务端派生的 format/profile。
- `/me/**`、购买与 viewer-state 响应使用 `Cache-Control: private, no-store`；公开 post/page/site GET 支持 ETag/Last-Modified 和显式 shared-cache 策略。
- 含可选 Bearer 的 post 响应不得被共享缓存混入 viewer state；匿名公共内容与个性化状态应拆分缓存键或拆分响应。
- Astro SSR 只缓存匿名公开响应；认证页面、callback、server action 和带 Set-Cookie 的响应不得进入 shared cache。
- 普通 FastAPI Error DTO、request ID、分页、并发和幂等合同沿用 `http-openapi.md`；Astro 保留安全 message/request ID，不向浏览器透传 token、provider body 或堆栈。

## 9. OpenAPI 与目录合同

根 `openapi.json` 继续表示完整产品 manifest。新增 `openapi.user.json` 与 hash，必须从同一个 FastAPI schema 按稳定 operation/tag allowlist 确定性投影，而不是维护第二套手写 API 规格；它只包含 `site`、`auth`、`user-center`、`posts`、`pages`、`discussions`、`community-tags` 及这些路径引用的 schema/security definition，不包含 `/api/v1/admin/**`、webhook 或运维接口。

计划目录：

```text
packages/
  markdown/                  # 纯 TS、版本化 gfm-v1 renderer；供 site SSR 与 admin preview 复用
site/
  astro.config.mjs
  package.json
  src/
    actions/               # 同源状态写入/BFF gateway
    components/
      astro/               # 默认无 hydration
      vue/                 # 显式交互 islands
    lib/
      api/
        generated/         # openapi.user.json 生成产物
        server/            # 仅服务端 Bearer API adapter
      auth/                # OIDC client 与 server session
      seo/                 # canonical/head/JSON-LD/sitemap/robots 纯生成逻辑
      markdown/            # server-only adapter，调用 packages/markdown
    middleware.ts
    pages/                 # Astro 文件路由，包含 robots.txt.ts/sitemap.xml.ts；不定义布局
  tests/
```

`site/src/lib/api/server` 必须通过 server-only 边界阻止被客户端 bundle 引入。页面和 Vue island 不直接拼 API URL；所有 FastAPI 调用集中于有路径 allowlist 的 adapter/action。

## 10. 实现顺序与发布门

1. 先增加 feature/manifest/router/OpenAPI 的失败合同测试，明确旧路由仍存在、新路由尚缺失的当前差距。
2. 建立 `user_center`，把签到、两类购买、`/me` 聚合与头像 workflow 声明迁入；保持 capability 所有权和 workflow key。
3. 把 engagement 投影 handler、post 互动及 comments 用户路由迁入 `post`；建立独立 `page` 公开 router；删除旧独立 feature/router 注册。
4. 按 community 规格增加失败合同测试、独立 migration/model/Command/Query/search projection 与 discussions/tags RouterSpec；不修改 content/taxonomy/comments 表。
5. 增加 backend Markdown policy 的失败合同测试，收敛 post/page/community schema、发布校验和 DTO；建立共享 `packages/markdown` 的恶意语料与 golden fixture。
6. 生成完整 OpenAPI 与用户投影，建立 `site/` 生成 client、SSR、OIDC BFF、Redis session、SEO 纯生成模块、Markdown server renderer 和基础错误/请求追踪。
7. 实现 Astro `robots.txt`、sitemap/index 分片、SSR head/JSON-LD 和稳定 SEO media 路由，并增加结构化输入、转义、环境隔离和缓存测试。
8. 增加独立用户站镜像/发布配置，以用户站和 API 不同 origin 运行真实 OIDC、SSR、Markdown 安全渲染、community 搜索/排序、SEO 文档、互动、评论、购买回调和 session 失效测试。

feature 收敛本身不应新增业务表或 migration；若实现发现必须增加持久化 readmodel/session 业务表，应先回到 capability/kernel 规格说明 owner。Astro session 存储属于用户站运行基础设施，使用 Redis namespace，不进入 FastAPI migration。

## 11. 验收

- 完整产品 manifest 的跨能力产品 feature 只有 `user_center`、`post`、`page`，另加显式站点/运维 feature；独立 `community` 作为 enabled capability 和 RouterSpec 产品面存在，不注册同名 feature；旧四个独立业务组装不再注册。
- `post` 启用时才出现 post/engagement/comments 用户路由和投影 handler；`page` 单独启用不产生 taxonomy、互动或评论副作用。
- community 未启用时 discussions/tags 用户与管理员路由均为 404 且不在完整/用户 OpenAPI；启用时仍不产生 content type、taxonomy assignment 或 comments target。
- `user_center` 未启用时，签到、购买、会员与本人积分扩展路由均为 404 且不在 OpenAPI。
- Astro 首屏 HTML 在禁用 JavaScript 时仍可完成匿名 post/page/community discussion 阅读与 Tags 浏览；只有声明为 Vue island 的交互需要 hydration。
- post/page API 只返回已校验的 Markdown 原文、format/profile/version，不返回派生 HTML；Astro 与管理员预览对同一 fixture 生成相同的已清洗正文结构。
- raw HTML、MDX、危险 URL、远程图片、超限正文和无效 asset reference 被稳定拒绝；发布门额外拒绝空 body、空 excerpt 和未 ready asset。
- community 的 latest/top/newest/relevance、tag filter 与 total 稳定；pending/hidden/deleted post 不进入公开 stream 或 search，GET 不写 view/read/search 事实。
- 渲染输出不能执行脚本、覆盖受保护 DOM ID 或泄露 provider/signed URL；renderer version 变化会使旧缓存失效。
- `robots.txt`、sitemap/index 分片和 SSR head/JSON-LD 全部由 Astro 生成；FastAPI/OpenAPI 不返回最终 HTML、XML 或 robots 文本。
- sitemap 只含 published/indexable post/page canonical，`lastmod` 可追溯；非生产环境强制全站禁止索引。
- canonical、`og:url`、sitemap 和 share image 使用用户站稳定 absolute URL，不使用 API origin 或短期 signed URL。
- 浏览器存储、HTML、Vue props、客户端 bundle、日志和错误中不存在 access/refresh token 或 OIDC client secret。
- 不同二级域名下的 login/callback/logout、CSRF、session rotation、401 refresh 单飞、CORS allowlist 和 Redis session 失效有真实集成测试。
- `openapi.json`、`openapi.user.json`、hash 与生成 TypeScript 类型无漂移；用户 adapter 无管理员/webhook 路径。
- 本轮不以任何页面布局、视觉稿或 UI 组件清单作为验收条件。
