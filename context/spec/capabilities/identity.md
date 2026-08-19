# Identity Capability 规格

## 1. 职责

identity 管理可登录或可被业务引用的用户主体、登录标识、密码凭据和账号状态。它不负责角色授权、OIDC 协议、浏览器 SSO session、通知发送或积分账户。

首版只有个人用户主体，不保留当前 Demo 的 Organization 占位模型。组织、多租户和外部身份联合需要未来独立规格。

## 2. 表所有权

建议表：

- `identity_users`：`id`、username、email_display、email_normalized、display_name、avatar_asset_id、status、email_verified_at、created/updated/deleted_at。
- `identity_login_identities`：user_id、provider key、provider_subject、verified、唯一约束。
- `identity_password_credentials`：user_id、password_hash、hash_version、changed_at、compromised_at。
- `identity_challenges`：邮箱验证/密码重置的一次性 opaque token digest、purpose、expires/consumed_at、attempts。

这些表只在 identity 内建立外键。`avatar_asset_id` 是指向 assets 的 opaque ID，不建立跨 capability 外键；不存在或不可用时读取结果返回无头像。

## 3. 用户状态

- `active`：允许通过身份认证，是否有业务权限由 access 决定。
- `banned`：拒绝新认证和敏感 Command，并触发会话撤销流程。
- `deleted`：不可认证，公开资料按删除策略最小化；保留必要审计引用。

状态转换必须由命名 Command 完成，不开放通用 status PATCH。

## 4. Commands

- `RegisterLocalUser`：创建用户、本地登录标识和密码凭据。
- `VerifyEmail`：一次性消费 challenge 并标记邮箱已验证。
- `RequestPasswordReset`：按登录标识（username/email 的 normalized 值）为 active 用户签发 `password_reset` 一次性 challenge，并作废该用户未消费的同类旧 challenge（新请求使旧 token 失效）。未知、banned 或 deleted 标识返回与成功等价的空结果（`None`），不泄露枚举。token 只在签发时返回给进程内调用方一次。
- `ChangePassword` / `ResetPassword`：校验策略、更新 hash version，并发布安全事件。challenge 不跨用途消费（`email_verification` token 不能重置密码，反之亦然）。
- `UpdateProfile`：只允许白名单资料字段。
- `LinkLoginIdentity` / `UnlinkLoginIdentity`：保证用户仍保有至少一种可用登录方式。
- `BanUser` / `UnbanUser` / `DeleteUser`：要求 access 权限并审计。

注册、验证、重置等需要邮件时由 feature/notification workflow 编排；identity 不导入 notification。

## 5. Queries 与提供的能力

- `GetSubject`、`FindByLoginIdentifier`、`ListUsers`、`GetPublicProfile`。
- 对消费方可提供 adapter，实现 `SubjectExists`、`SubjectClaimsReader`、`CredentialAuthenticator` 等由消费方定义的 Port。
- Query 返回最小必要 DTO；password hash、challenge digest 永不离开 capability 内部。

## 6. 规范化与凭据安全

- username 以明确的 Unicode/casefold 规则生成唯一 normalized 值，同时保留展示值。
- email 保存展示值与唯一 normalized 值；禁止实现 Gmail dot/plus 等 provider 特例。
- password policy、hash 算法和参数可版本化；验证成功后可以通过显式 Command 升级旧 hash。
- challenge/token 只保存 digest，必须短时有效、一次性消费、限次并使用常量时间比较。
- 用户枚举风险接口返回等价的外部响应和时序策略。

## 7. Events

- `identity.user_registered.v1`
- `identity.email_verified.v1`
- `identity.password_changed.v1`
- `identity.user_banned.v1`
- `identity.user_unbanned.v1`
- `identity.user_deleted.v1`

事件只携带必要 subject ID 和安全元数据，不携带 password、challenge token 或完整隐私资料。OIDC 会话撤销由 feature/oidc handler 消费安全事件完成。

## 8. 权限与审计

- 自助资料修改要求当前 subject 匹配。
- identity 的本人 Query 返回 `display_name`、`avatar_asset_id` 等原子资料；`GET /api/v1/me` 由 user_center 聚合头像、会员和可选积分摘要，读取不触发开户。
- identity 的 `UpdateProfile` 只允许当前 subject 修改受控资料字段；头像 upload/finalize 由 user_center 依次调用 assets 与 identity 的公开 Command，并写入 opaque asset ID。API 组合根只绑定 gateway/router，不执行业务步骤。
- `identity.users.read`、`identity.users.update`、`identity.users.ban`、`identity.users.unban`、`identity.users.delete` 为管理员能力 key。
- 密码、邮箱、封禁和删除均产生业务审计事件；敏感字段只记录变化类型，不记录原值。

## 9. Diagnostics 与指标

- 无可用登录方式的 active 用户。
- 重复/异常 normalized identifier。
- 未消费且过期的 challenge 积压。
- credential hash version 分布和认证失败率；用户 ID 不作为 metrics label。

## 10. 验收

- 并发注册同一 username/email 只能成功一次。
- challenge 重放、过期和猜测被拒绝。
- `RequestPasswordReset` 对未知、banned、deleted 标识返回与成功等价的外部结果；重复请求使旧 challenge 失效。
- ban/delete 后新认证失败并发出相应事实事件。
- 任何 DTO、日志、错误和事件不泄露 credential/challenge。
- identity 可在不导入 access、OIDC、assets 或 notification 的情况下测试。
