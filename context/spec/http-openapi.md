# HTTP 与 OpenAPI 规格

## 1. 边界

HTTP 是传输适配层。Router 只解析请求、建立 Principal/AppContext、执行授权、调用公开 Command/Query 并映射响应；不得访问 ORM/Repository 或承载跨能力业务逻辑。

普通业务 API 使用 `/api/v1`。OIDC 协议端点按 `capabilities/oidc-provider.md` 使用 issuer 下的标准路径和标准错误格式，不强行套入业务 API 前缀/错误 DTO。

管理员 SPA 的会话与业务读取统一消费 `/api/v1/admin/**`；共同公共面只包括 `/api/v1/auth/**` 的注册、验证与密码重置，以及 issuer 下的 OIDC 协议端点。管理员页面不得调用 `/api/v1/me` 或普通用户侧 content、community、points、membership、purchase、engagement 路由。该限制由前端 adapter 合同测试和 OpenAPI 路由测试共同守护。

Astro 用户站只消费由完整 schema 确定性投影的 `openapi.user.json`；其业务路径限定为 `site`、`auth`、`user-center`、`posts`、`pages`、`discussions`、`community-tags`。完整用户站、BFF 和端点矩阵见 [`用户站基础框架规格`](<../user site spec/user-site.md>)。

## 2. 基础端点

- `GET /healthz`：进程 liveness，不访问依赖。
- `GET /api/v1/health`：当前 manifest 的 readiness。
  readiness 必须同时探测数据库和管理员会话所需的 Redis；Redis 不可达时返回
  `status=degraded`，而不是静默退回进程内存。
- `GET /api/v1/admin/session`：当前管理员 Principal 的最小 identity 投影、当前 manifest 已注册且该主体实际拥有的 capability keys；不得返回用户站 points/membership 摘要，不得把数据库中的陈旧或未装配 permission key 投影给 SPA。
- `GET /api/v1/site`：匿名站点 bootstrap，只返回 allowlist 内的 public settings、类型化 SEO 输入和公开 feature 摘要；不返回最终 head/XML/robots 文本。
- `GET /api/v1/me`：当前 Principal、最小 subject profile、capability keys 和 `user_center` 装配的 points/membership 摘要；缺失账户或订阅不触发写入。
- `PATCH /api/v1/me`：当前 subject 自助修改 `display_name`、`avatar_asset_id`。
- `POST /api/v1/me/avatar/upload-intents`：当前 subject 为头像申请受限上传意图，组合根选择头像 bucket。
- `POST /api/v1/me/avatar/upload-intents/{intent_id}/finalize`：完成头像资产 workflow，将 ready asset ID 写回当前 subject 资料。
- `GET /api/v1/auth/grants`：当前认证 subject 的已授权应用列表；只返回未撤销的 OIDC consent，使用 `auth` tag，不区分用户侧和管理员端。
- `DELETE /api/v1/auth/grants/{client_id}`：当前认证 subject 撤销某应用授权；撤销 consent 并使该 subject/client 的 session 与 refresh family 失效，幂等返回 204，不要求管理员 capability。
- `POST /api/v1/auth/register`：公开自助注册（无需 Bearer）；username/email 冲突返回稳定 conflict 错误；注册即签发 email_verification challenge，token 只经带外投递（notification 装配前由进程内调用方持有），从不出现在响应体。
- `POST /api/v1/auth/verify-email`：公开端点；一次性 token 标记邮箱已验证，token 无效/已消费/过期返回稳定 validation 错误。
- `POST /api/v1/auth/password-reset/request`：公开端点（无需 Bearer）；对未知或非 active 标识返回与成功等价的 202 响应，不泄露枚举；challenge token 只经带外投递，从不出现在响应体。
- 登录失败按账号+来源地址在固定窗口内锁定并返回 429；密码重置请求按来源地址每小时最多 5 次并返回稳定 `auth.password_reset_rate_limited` 错误。注册端点不套用该限流。
- `POST /api/v1/auth/password-reset/confirm`：公开端点；一次性 token + 新密码，token 无效/已消费/过期返回稳定 validation 错误。
- `POST /api/v1/me/check-ins`：`user_center` 显式签到写端点（需认证）；幂等域为 subject + program + 业务日期，重复调用返回原结果。
- `GET /api/v1/me/points`：当前 subject 默认 program 的余额与安全桶摘要；未开户为逻辑零值。
- `GET /api/v1/me/points/ledger`：当前 subject 默认 program 积分账本分页；未开户返回空分页，读路径零副作用。
- `GET /api/v1/me/points/offers` / `POST /api/v1/me/points/orders`：受信积分价格目录读取与购买 workflow 启动（需认证 + `Idempotency-Key` 头）。
- `GET /api/v1/me/membership`、`GET /api/v1/me/membership/offers`、`POST /api/v1/me/membership/orders`：本人订阅摘要、受信会员目录与购买 workflow（写入要求 `Idempotency-Key`）。
- `GET /api/v1/me/purchases` / `GET /api/v1/me/purchases/{order_reference}`：只读本人购买安全摘要，不泄露 provider payload 或他人订单存在性。
- `GET /api/v1/me/favorites/posts`：当前 subject 已点赞 post 的稳定分页。
- `GET /api/v1/posts` / `GET /api/v1/posts/by-slug/{slug}`：`post` feature 的 published 列表与详情，允许匿名并可选 Bearer 读取 viewer state；GET 不计 view。`slug` 是服务端创建时生成、不可变的 `generated_title_suffix_v1` 路由键；未知与非 published 内容统一为 404，不接受 UUID/数值短码替代。
- `POST /api/v1/posts/{post_id}/views`、`PUT|DELETE .../like`、`PUT|DELETE .../rating`：`post` feature 的显式互动 Command；除 view 外均需认证。
- `GET|POST /api/v1/posts/{post_id}/comments`：`post` feature 绑定的评论读取/提交；提交需认证和 `Idempotency-Key`。
- `GET /api/v1/pages` / `GET /api/v1/pages/by-slug/{slug}`：`page` feature 的 published 目录与详情，不包含 taxonomy、engagement 或 comments。
- `GET|POST /api/v1/community/discussions`、`GET /api/v1/community/discussions/by-slug/{slug}`、`GET /api/v1/community/discussions/{discussion_id}/posts`、`POST /api/v1/community/discussions/{discussion_id}/replies`：community 的 discussion/post 产品面；公开列表支持 `q`、`tag` 和 `latest|top|newest`，GET 不写 view/read/search 事实。
- `GET /api/v1/community/tags` / `GET /api/v1/community/tags/by-slug/{slug}`：community 自有 Tags 分区，不读取通用 taxonomy。
- `POST /api/v1/webhooks/payments/{provider_key}`：支付 webhook；先取原始 bytes 验签（§8），duplicate receipt 返回已处理结果，不承担浏览器 Principal。
- `POST /api/v1/admin/users/{user_id}/unban`：管理员解封端点（`identity.users.unban` 权限）；仅 `banned` 用户可解封并发出 `identity.user_unbanned.v1` 安全事件，非 banned 返回稳定 conflict，未知用户返回 404。
- `POST /api/v1/admin/points/adjust`：管理员积分调整端点（`points.adjust` 权限）；`program_key` 可选，省略时使用 `credit`，请求携带 `reason` 与 `idempotency_key`，正数金额入 perpetual 桶，负数金额按 expires-at FIFO 扣桶（不足允许进入 debt），首次调整自动开户，重复 key 返回原流水结果；该写操作计入管理员审计。
- `GET /api/v1/admin/points/ledger`：按主体和可选 program 查询管理员积分账户余额、桶和账本分页（`points.read` 权限）；只读且无副作用。
- `GET /api/v1/admin/audit/entries`：按审计 action、actor、outcome 和时间范围分页查询不可变审计记录（`audit.read` 权限）。
- `GET /api/v1/admin/execution/entries`：按 kind、key、status 和时间范围分页查询 kernel outbox、inbox receipt、task 的安全执行摘要（`audit.read` 权限），不返回 payload/result/自由文本异常。
- `GET /api/v1/admin/assets`：按 state、provider、bucket 或 object key 分页查询稳定 asset references（`assets.read` 权限），不返回 signed URL。
- `GET /api/v1/admin/taxonomy/targets/{target_type}/{target_id}/terms`：读取一个 opaque target 的当前 term assignments（`taxonomy.read` 权限），按 dimension 分组返回；它不为 content 列表提供 taxonomy 过滤。
- `GET /api/v1/admin/notifications/deliveries` 与 `GET /api/v1/admin/notifications/deliveries/{delivery_id}`：查询 delivery、intent 与 attempt 安全摘要（`notification.read` 权限）；恢复面只导出 `POST .../retry` 和 `POST .../cancel` 命名 Command。
- capability/feature routers：只有完整产品 manifest 显式挂载后存在。

旧 `/api/v1/check-in`、`/api/v1/point-purchase/**`、`/api/v1/membership-purchase/**`、用户 `/api/v1/content/{type_name}/**`、通用 content comments 和 `/api/v1/me/favorites/{type_name}` 在 feature 收敛时删除，不保留兼容路由。

### 2.1 明确不导出的定义管理接口

- 管理员积分计划导出 `GET|POST /api/v1/admin/points/programs`、`PATCH /api/v1/admin/points/programs/{program_key}`、`POST .../activate|deactivate`、`GET .../summary` 和 `GET /api/v1/admin/points/accounts`；写入使用 expected_version/reason 并审计。
- 管理员会员等级导出 `GET|POST /api/v1/admin/membership/levels`、`PATCH /api/v1/admin/membership/levels/{level_key}`、`POST .../activate|archive` 以及会员 summary/subscriptions 工作台；归档阻止新订阅/续费但不影响当前周期。
- `notification template` 的定义管理由后端 capability/feature 注册表保留；当前不导出 `/api/v1/admin/notifications/templates` 的读取或写入接口。未来 notification 管理端点只覆盖 delivery/attempt 查询与命名恢复 Command，除非模板合同另行完成规格闭环。

上述 OpenAPI 缺席是刻意边界，不得通过反射数据库模型、自动 CRUD、前端手写 DTO 或占位页面绕过。未来导出必须逐项声明稳定 operationId、权限、版本/幂等、审计与错误合同。

payments 管理面导出订单分页、单笔 attempt/refund 摘要以及 cancel/reconcile/refund 语义 Command；禁止管理员直接 PATCH state 或 DELETE 账单。

OIDC 协议端点继续位于 issuer 标准路径；OIDC client 的管理员配置属于业务管理面，使用 `/api/v1/admin/oidc/clients`，只导出读取、注册、受限更新、启停和 secret rotation 语义操作。

旧 Demo endpoint 不是兼容目标。interaction 和旧 dashboard endpoint 删除；管理员汇总由显式 readmodel providers 形成新契约。

## 3. 请求和响应

- 请求/响应均使用 Pydantic DTO，拒绝未声明的安全敏感字段。
- Content-Type、body size、query 数量和字符串长度有全局上限；文件二进制不经本 API 上传。
- 成功响应直接返回资源 DTO 或 Page DTO，不再包一层无信息 envelope。
- 删除成功按端点语义返回 204 或结果 DTO，必须在 OpenAPI 固定。
- datetime 使用 UTC RFC 3339；UUID 为标准字符串；金额是 minor-unit integer + currency。
- post/page 详情与内容编辑响应中的 `body` 是规范化 Markdown 原文，并返回服务端派生的 `body_format`、`body_profile` 与内容 `version`；写请求不得提交 format/profile，响应不得包含 `rendered_html`。
- Markdown 上限按规范化后的 UTF-8 bytes 计算。OpenAPI description 与错误 response 必须声明该语义；JSON Schema `maxLength` 只能表达 code point 长度，不能冒充 byte 上限。

普通 API 错误：

```json
{
  "code": "content.invalid_transition",
  "message": "Content cannot be published from the current state.",
  "request_id": "...",
  "details": {}
}
```

`details` 只含安全、结构化、可选信息。validation error 也归一化，禁止返回堆栈、SQL、secret、token 或 provider payload。

## 4. Request ID 与追踪

- 客户端可传 `X-Request-ID`，服务端校验格式/长度；非法或缺失时生成。
- `X-Forwarded-For` 只有在 `AIYA_TRUSTED_PROXY_CIDRS` 命中的直接反代地址下才参与来源地址解析；未配置或不可信来源一律使用连接对端地址。
- 响应始终回传最终 request ID。
- correlation/trace ID 向 outbox、workflow 和外部 adapter 传播。
- 不信任客户端传入的内部 trace 权限或 actor 信息。

## 5. 认证和授权

- Bearer access token 由本系统 OIDC Provider 签发；API 校验签名、issuer、audience、expiry 和 scope。
- access capability 是业务权限最终边界；OIDC scope 不替代角色/资源授权。
- `require_capability` 或等价依赖调用 access 公共决策接口。
- 401 表示缺少/无效认证，403 表示已认证但拒绝；不得用 404 掩盖所有管理授权错误，除非资源存在性保密在端点规格明确。
- 前端传入 user/role/capability claims 不作为可信授权依据。

## 6. 幂等和并发

- 支付、积分、通知、工作流启动等可重试写端点要求 `Idempotency-Key` 或使用协议内稳定 key。
- 服务端按 principal/client + operation + key 建立作用域，重复同 payload 返回原结果；同 key 不同 payload 返回 conflict。
- 更新资源使用 version/ETag 或 DTO version 做乐观并发；冲突返回稳定错误。
- GET/HEAD 无业务副作用；任何计数、签到、埋点均使用显式写端点。

## 7. 分页、过滤和排序

Page DTO：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "size": 20
}
```

- page 从 1 开始，size 有默认值和上限。
- total 与 items 使用同一授权和过滤条件。
- 排序字段和方向使用 allowlist，最终带唯一稳定键。
- 未知过滤字段返回 validation error，不忽略。
- content 置顶分页使用 content 规格定义的全结果排序并占页容量。
- cursor endpoint 必须使用独立 DTO/文档，不能冒充 Page。

## 8. Webhook

- payment webhook router 必须取得原始 request bytes 后先验签，再构造业务 DTO。
- webhook 不使用浏览器 Principal，但使用 provider 身份、body 限制、时间窗、重放保护和速率限制。
- 对 provider 的响应语义由 adapter 固定，内部失败通过 receipt/workflow 恢复。
- 日志和错误不得回显签名、secret 或完整 payload。

## 9. CORS、Cookie 与 CSRF

- 生产允许 origin 使用精确 allowlist，不允许带 credential 的 `*`。
- 管理员 SPA 使用 Code + PKCE 启动登录；登录完成后由 FastAPI 以 Redis-backed
  `Secure + HttpOnly + SameSite=Lax` 会话 Cookie 承载浏览器请求，SPA 不持久化或
  发送 access/refresh token。程序化客户端仍可使用 Authorization header。
- Astro 用户站使用 confidential OIDC BFF：浏览器只持有用户站 host-only HttpOnly session ID，Astro server 持有 token 并以 Authorization header 调 API；FastAPI 不接受 Astro session cookie。
- 用户站基线的 Vue island 只调用同源 Astro action，不直接 fetch FastAPI，因此 FastAPI 对用户站 origin 不启用 credentialed CORS。未来浏览器直连必须逐端点另行定义，不能只扩大 allowlist。
- OIDC 登录 session cookie 必须 Secure/HttpOnly/SameSite 并有 CSRF/session fixation 防护；
  管理员写请求携带可读 CSRF Cookie 对应的 `X-CSRF-Token`，会话同时受空闲和绝对 TTL 约束。
- Astro BFF 的所有状态写 action 必须验证 Origin/Host、使用 CSRF token，并在登录、权限提升和登出时轮换/销毁 session。

## 10. OpenAPI

- 本轮根 `openapi.json` 和 `openapi.sha256` 是唯一可部署 `management_plane` 的冻结 HTTP 契约；完整产品 manifest 的 schema 仅作为延期用户站投影的开发 fixture。
- `openapi.user.json` 和对应 hash 是从同一完整 schema 按稳定 operation/tag allowlist 生成的用户站投影；不得手写第二套 schema，也不得包含 admin、webhook 或运维路径。
- `inc.api.openapi dump/check` 确定性生成管理面根快照，并从延期完整产品 fixture 生成用户站投影；两者均不得被手写。
- operationId、schema name、error response、security scheme 和 tags 必须稳定且唯一。
- 每个 router 声明稳定 tags 以组织 `/docs`：用户产品端点使用 `site`、`auth`、`user-center`、`posts`、`pages`、`discussions`、`community-tags`；协议/系统端点使用 `webhooks`、`oidc`、`system`；管理员端点使用伞形 `admin` tag 加 `admin-<domain>` 子 tag（如 `admin-users`、`admin-content`、`admin-community`）。tag 说明由组合根 `openapi_tags` 统一声明。
- 管理员 TypeScript 类型由 snapshot 生成，禁止手写重复后端 DTO 或以 `unknown` 绕过。
- Astro 用户站 TypeScript 类型只从用户投影生成；生成 adapter 必须以合同测试拒绝 admin/webhook 路径。
- 完整与用户 OpenAPI 都不得暴露内部 `TrustedHtml`、Markdown parser AST、sanitize 配置或派生 HTML schema；format/profile 是只读响应字段。
- API 变更必须在同一提交同步规格、失败测试、实现、完整/用户 snapshot 与 hash、生成类型和受影响前端调用。
- OIDC Discovery/JWKS 的动态内容另有协议合同测试，不把运行密钥固化进 OpenAPI。

## 11. RouterSpec

每个 RouterSpec 声明 owner、prefix、routes、所需 Command/Query、权限和 manifest 条件。API 组合根统一添加 middleware 和异常映射。

禁止：

- import 时 `include_router`。
- 根据数据库行或目录扫描自动创建 endpoint。
- 通过 subclass 反射自动生成 CRUD。
- endpoint 直接 import capability 的 models/repositories。

## 12. 验收

- 未启用 router 为 404 且不出现在 OpenAPI。
- 所有普通错误符合 Error DTO，所有 OIDC 错误符合协议。
- GET/HEAD 副作用测试、权限负向测试、分页稳定性和幂等重放测试通过。
- OpenAPI check 无漂移，管理员生成类型 typecheck 通过。
- `management_plane` schema 只含健康检查、`/api/v1/auth/**`、`/api/v1/admin/**` 和 issuer OIDC 协议端点；不含 `/api/v1/me` 或任何普通用户业务路径。
- 用户 OpenAPI 投影无 admin/webhook 路径，Astro 生成类型 typecheck/build 通过。
- CORS/CSRF/cookie/token cache headers 有生产配置测试。
- Markdown DTO 验证覆盖 UTF-8 byte 边界、只读 format/profile、稳定错误 code 和响应中不存在派生 HTML。
