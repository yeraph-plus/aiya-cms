# OIDC Provider Capability 规格

## 范围

本 capability 是 release 的 Authorization Server，支持登记 client 的 Authorization Code + PKCE、Discovery、JWKS、Token、UserInfo、Revocation 与 RP-Initiated Logout。管理员 SPA 是 public client；Astro SSR 客户端是 confidential server-side client。token、verifier、client secret 不得进入浏览器存储、HTML、Vue props 或日志。

OIDC 通过公开 identity/access Port 认证 opaque subject/claims/授权，不导入兄弟 capability 或表。code、refresh token、session handle 和 client secret 只存 digest；`oidc_signing_keys` 只存 public JWK、生命周期和 KeyRef。

## 持久签名 key

发布唯一实现是 `oidc.filesystem_keys`。`AIYA_OIDC_SIGNING_KEY_DIR` 必须是 backend 可读写的持久挂载目录；install 通过明确初始化命令生成 active key。私钥只在文件系统，目录和 key 文件使用 owner-only 权限，数据库/API/JWKS/日志/诊断不包含 PEM 或路径。

应用启动在 worker 前调用 `require_active_key()`。无 active row、KeyRef 无法读取、私钥缺失/损坏、JWK 不匹配或目录不可访问均抛 `oidc.signing_keys_unavailable` 并停止启动。测试在临时目录显式生成 filesystem key。没有内存 key store、开发 fallback 或 profile 例外。

key rotation 保持唯一 active key 和必要 verify-only 公钥；新 key 先出现在 JWKS，旧 key 至少保留至已签 token 最大有效期后。

## HTTP 与验收

OIDC 端点使用标准 OAuth/OIDC 响应，不套普通业务 Error DTO。release 的认证 HTTP 只服务公开浏览会话；它不扩大为用户资料、上传、购买或会员 API。

- key 缺失/损坏/无 active key 使启动失败；持久卷重启后可验证旧 token。
- redirect 精确匹配、PKCE、nonce、code replay、refresh rotation/reuse、logout/revocation 有负向测试。
- 内存 key、旧 profile 和密钥/路径泄露不可引用。
