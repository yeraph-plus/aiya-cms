# HTTP 与 OpenAPI 规格

## 1. 边界

HTTP 是传输适配层。Router 只解析请求、建立 Principal/AppContext、执行授权、调用公开 Command/Query 并映射响应；不得访问 ORM/Repository 或承载跨能力业务逻辑。

普通业务 API 使用 `/api/v1`。OIDC 协议端点按 `capabilities/oidc-provider.md` 使用 issuer 下的标准路径和标准错误格式，不强行套入业务 API 前缀/错误 DTO。

管理员 SPA 除共同认证面外只消费 `/api/v1/admin/**`：共同认证面包括 `/api/v1/auth/**`、带 `auth` tag 的 `/api/v1/me` 投影和 issuer 下的 OIDC 协议端点。管理员页面不得调用普通用户侧 content、points、membership、purchase 或 engagement 路由。该限制由前端 adapter 合同测试和 OpenAPI 路由测试共同守护。

## 2. 基础端点

- `GET /healthz`：进程 liveness，不访问依赖。
- `GET /api/v1/health`：当前 manifest 的 readiness。
- `GET /api/v1/me`：当前 Principal、最小 subject profile、capability keys 和已装配的用户摘要（当前包含 points 余额）。
- `PATCH /api/v1/me`：当前 subject 自助修改 `display_name`、`avatar_asset_id`。
- `POST /api/v1/me/avatar/upload-intents`：当前 subject 为头像申请受限上传意图，组合根选择头像 bucket。
- `POST /api/v1/me/avatar/upload-intents/{intent_id}/finalize`：完成头像资产 workflow，将 ready asset ID 写回当前 subject 资料。
- `GET /api/v1/auth/grants`：当前认证 subject 的已授权应用列表；只返回未撤销的 OIDC consent，使用 `auth` tag，不区分用户侧和管理员端。
- `DELETE /api/v1/auth/grants/{client_id}`：当前认证 subject 撤销某应用授权；撤销 consent 并使该 subject/client 的 session 与 refresh family 失效，幂等返回 204，不要求管理员 capability。
- `POST /api/v1/auth/register`：公开自助注册（无需 Bearer）；username/email 冲突返回稳定 conflict 错误；注册即签发 email_verification challenge，token 只经带外投递（notification 装配前由进程内调用方持有），从不出现在响应体。
- `POST /api/v1/auth/verify-email`：公开端点；一次性 token 标记邮箱已验证，token 无效/已消费/过期返回稳定 validation 错误。
- `POST /api/v1/auth/password-reset/request`：公开端点（无需 Bearer）；对未知或非 active 标识返回与成功等价的 202 响应，不泄露枚举；challenge token 只经带外投递，从不出现在响应体。
- `POST /api/v1/auth/password-reset/confirm`：公开端点；一次性 token + 新密码，token 无效/已消费/过期返回稳定 validation 错误。
- `POST /api/v1/check-in`：显式签到写端点（需认证）；幂等域为 subject + program + 业务日期，重复调用返回原结果。
- `GET /api/v1/me/points/ledger`：当前 subject 默认 program 积分账本分页；未开户返回空分页，读路径零副作用。
- `GET /api/v1/point-purchase/offers` / `POST /api/v1/point-purchase/orders`：受信价格目录读取与购买 workflow 启动（需认证 + `Idempotency-Key` 头）。
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

### 2.1 明确不导出的定义管理接口

- `points program` 的定义管理由后端代码/ops 保留；当前不导出 `/api/v1/admin/points/programs` 的 GET/POST/PATCH/DELETE。现有 points 端点只消费已注册的 `program_key`。
- `membership level` 的定义管理由后端代码/ops 保留；`GET /api/v1/admin/membership/levels` 是只读目录，当前不导出 POST/PATCH/DELETE 或通用状态写入。
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
- 管理员 SPA 默认 Code + PKCE、内存 access token，以 Authorization header 调 API。
- OIDC 登录 session cookie 必须 Secure/HttpOnly/SameSite 并有 CSRF/session fixation 防护。
- 若未来增加 BFF/httpOnly application session，所有状态写请求必须加入与部署模式匹配的 CSRF 保护，并单独更新规格。

## 10. OpenAPI

- 根 `openapi.json` 和 `openapi.sha256` 是完整产品 manifest 的冻结 HTTP 契约。
- `inc.api.openapi dump/check` 或替代命令以同一 manifest 确定性生成。
- operationId、schema name、error response、security scheme 和 tags 必须稳定且唯一。
- 每个 router 声明稳定 tags 以组织 `/docs`：公开端点使用领域 tag（`auth`、`check-in`、`points`、`point-purchase`、`membership-purchase`、`webhooks`、`oidc`、`system`）；管理员端点使用伞形 `admin` tag 加 `admin-<domain>` 子 tag（如 `admin-users`、`admin-content`）。tag 说明由组合根 `openapi_tags` 统一声明。
- 管理员 TypeScript 类型由 snapshot 生成，禁止手写重复后端 DTO 或以 `unknown` 绕过。
- API 变更必须在同一提交同步规格、失败测试、实现、snapshot/hash、生成类型和管理员调用。
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
- CORS/CSRF/cookie/token cache headers 有生产配置测试。
