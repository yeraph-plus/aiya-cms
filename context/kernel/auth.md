# Kernel / auth

## 1. 设计目的

认证流程：注册、登录、双令牌刷新、吊销、当前主体解析。只支持 password Provider（OAuth 预留）。

非目标：找回密码/邮箱验证流程（mail 就绪后补，路由预留）；OAuth 回调（identity.md 已预留）。

## 2. 范围与依赖

- 代码位置: `inc/kernel/auth/`
- 依赖的 kernel 组件: db, security, identity, rbac, events, errors, logging, cache（登录限频）
- 被谁依赖: api deps（`get_current_principal`）
- 外部依赖: 无新增

## 3. 领域模型

- **注册**：username + email + password → 创建 User + password Identity（provider_uid=email）→ 默认角色 `reader` → `user.registered`。
- **登录**：identifier（username 或 email）+ password → 校验 → 装配 Principal（roles+capabilities 实时查询）→ 签发 access + refresh（refresh 哈希落 `refresh_tokens`）→ `user.login_succeeded`。失败 → `user.login_failed` + Cache 限频计数（同 identifier/IP 5 次/5 分钟，超限 AUTH_007）。
- **刷新**：raw refresh → 查哈希匹配且未吊销未过期 → 旋转（旧吊销、新签发）→ 新双令牌。
- **吊销**：登出吊销当前 refresh；改密/封禁吊销该用户全部 refresh。

## 4. 状态机

refresh_tokens 生命周期：

| 状态 | 含义 | 转换 |
|---|---|---|
| active | 可用 | 过期（expires_at）→ expired；rotate/revoke → revoked（revoked_at 落时间） |

## 5. 数据库

### 表: `refresh_tokens`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| user_id | uuid | FK users.id, not null | |
| token_hash | str(128) | unique, not null | 仅存哈希 |
| expires_at | timestamptz | not null | |
| revoked_at | timestamptz | null | |
| last_used_at | timestamptz | null | |
| user_agent | str(256) | null | |
| ip | str(64) | null | |
| created_at | timestamptz | not null | |

索引: `ix_refresh_tokens_user_id`

JSONB 字段对应的 Pydantic Model: 无。

## 6. 公开 API

```python
class AuthService(Protocol):
    async def register(self, dto: RegisterRequest) -> UserRead
    async def bootstrap_admin(self, dto: RegisterRequest) -> UserRead
    async def login(self, dto: LoginRequest, *, ip: str, user_agent: str) -> TokenPair
    async def refresh(self, raw_refresh: str) -> TokenPair
    async def logout(self, raw_refresh: str) -> None

def get_current_principal(...) -> Principal  # FastAPI 依赖；匿名→匿名 Principal
```

### HTTP API

| 方法 | 路径 | Capability | 请求 DTO | 响应 DTO | 说明 |
|---|---|---|---|---|---|
| POST | /api/v1/auth/register | 公开 | RegisterRequest | UserRead | |
| POST | /api/v1/auth/login | 公开 | LoginRequest | TokenPair | 限频 |
| POST | /api/v1/auth/refresh | 公开 | RefreshRequest | TokenPair | 旋转 |
| POST | /api/v1/auth/logout | 登录 | RefreshRequest | 204 | 吊销 |
| GET | /api/v1/auth/me | 登录 | — | UserRead + capabilities | |

浏览器会话（管理员 SPA）下，login/refresh 在返回 TokenPair 的同时通过 `Set-Cookie` 写入 httpOnly refresh cookie（`SameSite=Strict; Path=/api/v1/auth`）；refresh/logout 的权威 refresh 来源为 cookie，`RefreshRequest` 保留供非浏览器消费者。详见 [ADR-0013](../adr/0013-browser-token-storage-cors-csrf.md)。

## 7. Pipeline

无。

## 8. Event

- 发布: `user.registered` `{user_id}`、`user.login_succeeded` `{user_id, ip}`、`user.login_failed` `{identifier, ip, reason}`、`user.password_changed` `{user_id}`。
- 订阅: 无（审计监听器在 audit.md 消费这些事件）。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| AUTH_001 | 401 | 凭据无效 | 密码错误/用户不存在（统一口径防枚举） |
| AUTH_004 | 409 | 邮箱已注册 | register |
| AUTH_005 | 409 | 用户名已占用 | register |
| AUTH_006 | 403 | 用户被禁用/已注销 | login 时 status != active |
| AUTH_007 | 429 | 登录尝试超限 | 限频触发 |

## 10. Cron / 任务

- `auth.purge_expired_tokens`（每日 04:10）：物理删除 `expires_at < now-7d` 且已吊销/过期的 refresh_tokens。系统 bot 运行，写审计。

## 11. 测试边界

- 注册→登录→me→refresh→logout 全链路；logout 后旧 refresh 再用 → AUTH_003。
- refresh 旋转后旧 token 立即失效（重放保护）。
- 登录失败 5 次触发 AUTH_007；时间窗过后恢复。
- 封禁用户登录 → AUTH_006；封禁即刻吊销全部 refresh。
- 注册同时建 reader 角色与 password Identity（一条事务）。
- `bootstrap_admin` 在已迁移数据库中以单个事务创建用户、password Identity 和 admin 角色关联；重复用户名/邮箱拒绝，不提供公开 HTTP 路由。
- AUTH_001 对"用户不存在"与"密码错误"响应完全一致。

## 12. 未决事项

- 邮箱验证（verified=true）与找回密码：待 mail 组件，路由预留 `/auth/verify-email`、`/auth/forgot-password`。
- OAuth：新增 `/auth/oauth/{provider}/callback`，走 identities(provider, provider_uid) 匹配，无需表变更。

## 13. M1.8 实现状态

M1.8 已实现（2026-08-04）：`AuthService`、`AuthUnitOfWork`、`refresh_tokens`
迁移（`0004_auth`）以及注册/登录/refresh rotation/logout/me 的 DTO 与事件模型
已落库。注册在单个 UoW 中创建用户、password Identity 和 reader 角色关联；登录
使用 Argon2 校验并生成 access JWT 与 opaque refresh；refresh 对旧 token 做行级
锁定与吊销，重放统一返回 `AUTH_003`。失败登录按 normalized identifier + IP
限频，事件在写事务提交后发布。API 路由与 Cookie/CSRF 装配仍按 M1.12 处理。
