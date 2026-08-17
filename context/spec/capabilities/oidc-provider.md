# OIDC Provider Capability 规格

## 1. 职责和安全基线

本系统作为 OpenID Provider/Authorization Server，向管理员 SPA 和其他登记应用提供单点登录。首版采用 Authorization Code Flow，不实现外部身份提供商兼容或动态客户端注册。

规范基线：

- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0-final.html)
- [OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0-final.html)
- [OAuth 2.0 Security Best Current Practice, RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html)
- [PKCE, RFC 7636](https://www.rfc-editor.org/rfc/rfc7636.html)
- [Token Revocation, RFC 7009](https://www.rfc-editor.org/rfc/rfc7009.html)
- [OpenID Connect RP-Initiated Logout 1.0](https://openid.net/specs/openid-connect-rpinitiated-1_0-final.html)

若本规格与上述规范在协议字段或安全要求上冲突，以规范和通过的 conformance profile 为最低要求，再更新本规格。

## 2. 首版协议范围

必须支持：

- `response_type=code`。
- public client 使用 PKCE `S256`；confidential client 也默认要求 PKCE。
- Discovery、Authorization、Token、UserInfo、JWKS、Revocation。
- 静态/管理员管理的 client registration。
- refresh token rotation 和 reuse detection。
- RP-Initiated Logout。
- `openid`、`profile`、`email` 和注册的 API scopes。

首版不支持 implicit、hybrid、resource owner password、dynamic registration、device flow、Federation、FAPI、front-channel/back-channel logout。未来添加必须单独更新范围、威胁模型和 conformance gate。

## 3. 端点

issuer 由配置提供且生产必须是 HTTPS、无 query/fragment。默认端点：

- `/.well-known/openid-configuration`
- `/oidc/authorize`
- `/oidc/token`
- `/oidc/userinfo`
- `/oidc/jwks`
- `/oidc/revoke`
- `/oidc/logout`

Discovery 返回值必须从同一 canonical issuer 构建，声明实际支持的 response/grant、subject、signing、client auth 和 PKCE methods。协议错误使用 OAuth/OIDC 标准响应，不套普通 API Error DTO。

`POST /oidc/login` 同时支持浏览器 HTML 表单和管理员 SPA 的 JSON negotiation。SPA 请求使用 `Accept: application/json`，成功响应返回带 code/state 的前端 callback URI，失败响应返回标准 OIDC JSON error；该模式不得通过 3xx 将错误导航到 OP 页面。

## 4. Port 边界

OIDC 自己声明并消费：

- `SubjectAuthenticator`：验证当前交互登录主体。
- `SubjectClaimsReader`：按授权 scope 返回最小 claims。
- `AuthorizationDecisionReader`：判断主体是否可授权某 scope/resource。
- `SecurityEventSubscriber`：接收密码变更、封禁等事实并撤销 grant/session。

这些 Port 由组合根通过 identity/access 公开入口实现；OIDC 不导入它们的代码或表。

## 5. 表所有权

- `oidc_clients`：client_id、type、名称、redirect/post-logout URI、grant/response types、auth method、allowed scopes/audiences、状态。
- `oidc_client_secrets`：仅 confidential client，保存 secret digest/version/expiry，不保存明文。
- `oidc_authorization_codes`：code digest、client、subject ref、redirect URI、scope/audience、nonce、PKCE challenge、expires/consumed_at。
- `oidc_grants_consents`：subject ref、client、获准 scope/audience、时间和撤销状态。
- `oidc_sessions`：subject ref、auth time、ACR/AMR、浏览器 session digest、expires/revoked_at。
- `oidc_refresh_families` 与 `oidc_refresh_tokens`：family、token digest、generation、scope/audience、expires/rotated/revoked/reused_at。
- `oidc_signing_keys`：kid、algorithm、public JWK、KeyRef、not-before/retire/delete times；私钥本体不得明文入库。

所有 code、refresh token、session handle、client secret 只保存 digest。OIDC 对 subject 只保存 opaque reference，不建 identity 外键。

## 6. Authorization 请求

- client 必须 active，redirect URI 使用预注册值精确匹配；native localhost 例外仅在未来明确支持时启用。
- 只接受登记的 response type、scope、audience 和 response mode。
- public client 强制 `code_challenge_method=S256`；存在 verifier 而原请求无 challenge 的降级尝试必须拒绝。
- 管理员 SPA 等浏览器 OIDC client 必须发送并校验 transaction-specific `state`、`nonce` 和 PKCE。
- authorization code 与 client、subject、redirect URI、scope、audience、nonce 和 challenge 绑定，短时有效且只能消费一次。
- 禁止 open redirect；登录/consent 页面不得把 credential 或 code 泄漏到不受信 Referer。

## 7. Token 与 claims

- ID token 使用当前 active 非对称 key 签名，包含正确 `iss`、`sub`、`aud`、`exp`、`iat`、`auth_time`、`nonce`（请求存在时）和必要 `azp`。
- access token 首版使用受众受限的短期 JWT；resource server 必须校验签名、issuer、audience、expiry 和授权 scope。
- refresh token 为高熵 opaque token，绑定 client、subject、grant、scope 和 audience。
- token response 设置 `Cache-Control: no-store` 和 `Pragma: no-cache`。
- `sub` 对一个 issuer 稳定；首版使用 public subject，pairwise subject 延后。
- scope 最小授权；UserInfo 只返回 token 已授权 claims。

## 8. Refresh rotation 与撤销

- public client 若签发 refresh token，必须每次使用后旋转。
- 旧 token 的关系保留；检测到已旋转 token 重用时撤销整个 family，并记录安全事件。
- refresh token 具有 absolute 与 inactivity expiry。
- password change、user ban/delete、client disable、logout 或管理员撤销可以撤销相关 session/grant/family。
- revocation endpoint 对未知 token 返回协议允许的幂等成功语义，不泄露 token 是否存在。

## 9. Client 管理和 consent

- 首版只允许管理员 API/ops Command 管理 client；不暴露 Dynamic Client Registration 协议。
- 管理员 HTTP 面固定为 `/api/v1/admin/oidc/clients`：列表/单项读取调用 `ClientQueries`，注册、更新 redirect/scope、启用、禁用与 confidential secret rotation 分别调用具名 Command；不允许通用 PATCH 任意协议状态，也不回显历史 secret。系统管理员客户端 `client_id=admin` 是受保护客户端，管理员端不展示禁用操作，后端也必须拒绝禁用请求；启用操作仍可用于恢复历史误禁用数据。
- redirect URI、post logout URI 以完整字符串集合保存，不支持通配符。
- public client auth method 为 `none`；confidential client 首版支持 `client_secret_basic`。
- trusted first-party client 可以配置跳过重复 consent，但 scope 仍受注册和 access 决策约束。
- post logout redirect 必须精确匹配已登记 URI；有 redirect 时要求有效 `id_token_hint` 或等价的已验证 client/session 上下文。

用户自服务授权管理属于普通 `auth` API 组，不属于管理员 API：

- `GET /api/v1/auth/grants` 只按当前认证 subject 查询 `revoked_at IS NULL` 的 consent，返回 `client_id`、可展示的 `client_name`（client 已不存在时为 null）、获准 `scopes`、`audiences` 和 `granted_at`，按 `client_id` 稳定排序。
- `DELETE /api/v1/auth/grants/{client_id}` 只允许作用于当前认证 subject，保留 consent 行并写入 `revoked_at`；同时撤销该 subject/client 的 OIDC session、refresh family 和 refresh token。不存在或已撤销的 consent 使用幂等 204，不泄露授权是否存在。
- 上述两个端点只要求有效 Bearer，不要求 `oidc_provider.grants.revoke` 管理员 capability；后端仍从认证上下文取得 subject，禁止客户端提交 subject_id。

## 10. 密钥轮换

- 同时只有一个签发 active key，可以保留多个 verify-only 公钥。
- 新 key 在签发前先发布到 JWKS；旧 key 至少保留到所有已签 token 最大寿命和时钟偏移之后。
- `kid` 全局唯一，不复用；算法 allowlist，不接受 token 自报未知算法。
- KeyRef 指向环境 secret、文件或 KMS；日志/诊断只显示 kid 和生命周期。
- 当前生产 `management_plane` 使用 `oidc.filesystem_keys` KeyRef adapter；`AIYA_OIDC_SIGNING_KEY_DIR` 指向只由 backend 非 root 用户读写的持久卷。进程/容器替换后必须仍能按数据库 KeyRef 读取同一私钥；`oidc.in_memory_keys` 只允许开发/测试 profile，生产绑定启动失败。

## 11. 管理员 SPA

- 作为 first-party public client 使用 Code + PKCE S256。
- access token 仅保存在内存，不落 localStorage/sessionStorage。
- 首版若需要跨刷新长期会话，优先增加 BFF/httpOnly session adapter；不得把 provider 的 refresh token 写入浏览器持久存储。
- OIDC session cookie 为 `Secure`、`HttpOnly`、合适的 `SameSite`，并具备 CSRF 和 session fixation 防护。

### 11.1 Astro 用户站 BFF

- 用户站是静态登记的 first-party confidential client，使用 Authorization Code + PKCE S256；client secret 只存在 Astro server 环境配置。
- callback 由 Astro server 消费；access/refresh token、code verifier 和 client secret 不进入 HTML、Vue props、浏览器持久存储或客户端 bundle。
- Astro 使用 Redis-backed server session，浏览器只保存用户站 origin 的 host-only HttpOnly session ID cookie；FastAPI 资源 API 只接受 Astro BFF 转发的 Bearer，不接受该 application session cookie。
- refresh rotation/reuse detection、revocation和 RP-Initiated Logout 继续由本 capability 执行；BFF 必须单飞刷新并在失败、reuse 或 logout 后销毁本地 session。
- 用户站与 issuer 可以位于同一 registrable domain 的不同二级域名，但 redirect/post-logout URI 仍完整字符串精确匹配；不得依赖跨子域共享 application cookie。

## 12. 审计、诊断和限流

- 审计 client 变更、授权、token issuance、revocation、logout、key rotation、code replay 和 refresh reuse；不记录 token/code/secret。
- authorization/token/login/revocation 按 client、IP 风险和 subject 进行受控限流，避免把高基数值放入 metrics label。
- diagnostics 检查过期 code/token 清理积压、无 active signing key、JWKS 生命周期错误、异常 reuse 和 disabled client 活动。
- `cleanup_expired_keys` 由组合根注册为 `oidc.keys.cleanup.v1` Cron task；未装配 oidc_provider 时不产生该 task。

## 13. 验收

- redirect 精确匹配、PKCE downgrade、code replay、client binding、nonce、issuer/audience、算法混淆均有负向测试。
- refresh 正常旋转、并发使用和 reuse detection 撤销 family 有并发测试。
- key rotation 窗口内新旧 token 均按预期验证，过窗后旧 key 删除安全。
- logout/revocation 不产生开放重定向或 token existence oracle。
- 通过 OpenID Foundation Basic OP、Config OP 和适用的 RP-Initiated Logout conformance 测试；不要求未支持的 implicit/hybrid/dynamic profiles。
