# ADR-0020: Security 原语与令牌边界

- 状态: accepted
- 日期: 2026-08-04
- 关联: [kernel/security.md](../kernel/security.md)、[kernel/config.md](../kernel/config.md)、[ADR-0013](0013-browser-token-storage-cors-csrf.md)

## 决策

1. 密码只经 `pwdlib` 的 Argon2id `PasswordHash.recommended()` 哈希；校验失败（包括未知/损坏哈希）统一返回 `False`，不把哈希实现细节泄露给调用方。
2. access token 使用 HS256，载荷固定包含 `sub`、`roles`、`capabilities`、`iat`、`exp` 和 `type=access`；验证时必须检查签名、必需声明、令牌类型、UUID subject 和过期时间。
3. refresh token 使用高熵不透明随机字符串；持久化值只保存 SHA-256 摘要，原始 token 只在签发响应中返回。refresh rotation、吊销和数据库表由 M1.8 auth 负责。
4. 过期令牌映射 `AUTH_002`，其他格式/签名/类型/声明错误映射 `AUTH_003`。Security 原语不实现登录流程，也不访问数据库。

## 后果

- 认证流程可以在不依赖数据库的情况下测试签发与校验边界。
- access token 的角色/能力是登录时快照；RBAC 的重新装配由 auth 调用 `RBACService.build_principal` 完成。
- 更换签名算法或密钥轮换需要新增 ADR；本期不引入 JWK/OAuth provider。
