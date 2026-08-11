# Access Capability 规格

## 1. 职责

access 管理权限 key 注册、角色、主体角色关联和授权决策。它不认证密码、不签发 token、不拥有用户表，也不决定 OIDC 协议响应。

后端 access policy 是最终授权边界；前端权限只控制可见性和交互。

## 2. 权限注册

- capability/feature 在 definition 中登记自己拥有的权限 key、说明和风险级别。
- key 使用 `<owner>.<resource>.<action>` 或精简的 `<owner>.<action>`，例如 `content.publish`、`points.adjust`。
- 未登记权限不能绑定 router/Command；重复 key 启动失败。
- 权限 key 随发布成为稳定合同，重命名必须带角色数据迁移。

## 3. 表所有权

- `access_roles`：name、slug、description、system flag。
- `access_role_capabilities`：role_id、capability key。
- `access_subject_roles`：subject_type、subject_id、role_id、scope、有效时间。

subject 是 identity 等能力的 opaque reference，不建立外键。创建关联前通过 access 自己声明的 `SubjectExists` Port 校验。

## 4. Commands

- `CreateRole`、`UpdateRole`、`DeleteRole`。
- `ReplaceRoleCapabilities`。
- `AssignRoleToSubject`、`RevokeRoleFromSubject`。
- `BootstrapAdministrator`：仅 `install` ops 入口可调用。系统内只允许一个超级管理员（`administrator` 角色）：目标 subject 已持有该角色时幂等返回；已有其他 subject 持有该角色时拒绝并返回 `access.administrator_exists`，禁止创建第二个超级管理员。bootstrap 创建 `administrator` 系统角色并绑定全部已注册权限 key。

系统角色允许禁止删除或限制编辑。任何 role/capability 变更必须在一个 access UoW 中保持一致并审计。

## 5. 授权决策

`Authorize(principal, capability_key, resource_context)` 返回 allow/deny 和内部 reason code：

- 默认拒绝。
- banned/deleted/匿名主体的行为由 Principal 状态和目标权限明确判定。
- scope 可以限制到 own/tenant/resource；首版至少支持 global 与 own 语义。
- API 的 `require_capability` 只调用 access 公共决策接口，不自行复制角色逻辑。
- 不允许前端提供 capabilities 声明作为可信输入。

## 6. Principal

Principal DTO 可以包含 subject ref、authentication method、session/client ID 和已计算 capability set，但不得包含 ORM 或 secret。Principal 的生成由认证 adapter 完成，access 负责授权解释。

长期 token 中的权限 claim 不作为唯一事实来源；敏感操作必须允许按当前 access 状态重新决策或使用短期缓存版本。

## 7. Events

- `access.role_changed.v1`
- `access.subject_role_assigned.v1`
- `access.subject_role_revoked.v1`
- `access.capability_registry_changed.v1` 只在部署/注册版本变化时使用，不由普通请求产生。

## 8. 审计与诊断

- 角色创建、权限替换、主体绑定/解除和 bootstrap 全部审计 actor、target 和 request ID。
- diagnostics 检查未知 capability key、失效 subject 引用、无管理员主体和非法 system role 变更。
- 修复孤儿关联必须是单独 dry-run Command，不由 diagnostics 自动删除。

## 9. 验收

- 未登记权限、重复权限和 router 未声明权限均阻止启动。
- 默认拒绝、own/global scope 和实时撤权有正负测试。
- 并发 ReplaceRoleCapabilities 不产生部分集合。
- access 不导入 identity/OIDC；SubjectExists 由组合根绑定。
- `install` 在空库一步完成迁移、points 种子与单一超级管理员 bootstrap 并留下审计记录；重复执行不产生第二个超级管理员，与其他 subject 冲突时失败。
- 本期不提供管理员 CLI 密码找回，也不提供 CLI 直接创建/删除用户等平面操作。
