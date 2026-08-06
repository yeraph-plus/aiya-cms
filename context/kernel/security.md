# Kernel / security

## 1. 设计目的

认证原语：密码哈希、JWT 签发与校验、请求主体 `Principal` 抽象。只提供原语，不实现登录流程（流程在 [auth.md](auth.md)）。

非目标：不处理 OAuth 协议细节（预留 Provider 维度，实装后期）。

## 2. 范围与依赖

- 代码位置: `inc/kernel/security/`
- 依赖的 kernel 组件: config, errors, logging
- 被谁依赖: auth, rbac, api deps
- 外部依赖: pwdlib[argon2], PyJWT

## 3. 领域模型

- `Principal`（Pydantic）：当前请求主体。
  - `id: UUID`、`username: str`、`roles: frozenset[str]`、`capabilities: frozenset[str]`、`is_system_bot: bool`、`is_anonymous: bool`。
  - 匿名请求也有 Principal（is_anonymous=True，空集合）——下游永远有主体，不需要 None 判断。
  - 系统 bot：Cron/内部任务的运行主体（is_system_bot=True），capabilities 由任务声明注入，不可登录。
- `hash_password(plain) -> str` / `verify_password(plain, hashed) -> bool`（argon2id）。
- `TokenService`：`issue_access(principal) -> str`、`issue_refresh(user_id) -> tuple[str, str]`（返回 raw token 与 hash）、`verify_access(token) -> PrincipalClaims`、`hash_refresh(raw) -> str`。refresh token 只存哈希（表见 auth.md）。

## 4. 状态机

无。

## 5. 数据库

无（refresh token 持久化属 auth 组件）。

## 6. 公开 API

```python
class Principal(BaseModel): ...
def hash_password(plain: str) -> str
def verify_password(plain: str, hashed: str) -> bool
class TokenService: ...
```

### HTTP API

无。

## 7. Pipeline

无。

## 8. Event

无。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| AUTH_002 | 401 | 令牌过期 | access/refresh 过期 |
| AUTH_003 | 401 | 令牌无效 | 签名错误、格式错误、吊销 |

## 10. Cron / 任务

无。

## 11. 测试边界

- 哈希往返：verify(hash(p)) 为真；错误密码为假；哈希串不含明文。
- access token 含 sub/roles/capabilities/exp；过期后 verify 抛 AUTH_002。
- 篡改签名的 token → AUTH_003。
- refresh 只存哈希：DB 泄露不可还原 token（hash_refresh 单向）。
- Principal 匿名构造：空 roles/capabilities，is_anonymous=True。

## 12. 未决事项

- OAuth Provider 抽象（`OAuthProvider` Protocol + provider_uid 映射 identities）：字段已预留，实装待后期模块。

## 13. 实现边界（M1.4）

- `hash_password` / `verify_password` 使用 `pwdlib.PasswordHash.recommended()` 的 Argon2id；空密码拒绝，损坏哈希按不匹配处理。
- `TokenService.issue_access` 签发 HS256 JWT，载荷包含 `sub`、`roles`、`capabilities`、`iat`、`exp`、`type=access`；`verify_access` 严格校验签名、声明、类型和 UUID subject。
- `issue_refresh` 生成高熵不透明 token，并返回 `(raw, sha256_digest)`；只允许 auth 组件持久化摘要，Security 不接触数据库。
- 过期映射 `AUTH_002`，其他令牌错误映射 `AUTH_003`；完整登录、rotation、吊销由 M1.8 Auth 实现。
