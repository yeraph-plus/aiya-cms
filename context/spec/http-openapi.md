# HTTP 与 OpenAPI 规格

## 1. 边界

HTTP 是传输适配层。Router 只解析请求、建立 Principal/AppContext、执行授权、调用公开 Command/Query 并映射响应；不得访问 ORM/Repository 或承载跨能力业务逻辑。

普通业务 API 使用 `/api/v1`。OIDC 协议端点按 `capabilities/oidc-provider.md` 使用 issuer 下的标准路径和标准错误格式，不强行套入业务 API 前缀/错误 DTO。

## 2. 基础端点

- `GET /healthz`：进程 liveness，不访问依赖。
- `GET /api/v1/health`：当前 manifest 的 readiness。
- `GET /api/v1/auth/me`：当前 Principal、最小 subject profile 和 capability keys。
- capability/feature routers：只有完整产品 manifest 显式挂载后存在。

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
