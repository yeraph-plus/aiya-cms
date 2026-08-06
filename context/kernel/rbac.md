# Kernel / rbac（Role / Permission / Policy）

> ADR-0032 将 Content/Taxonomy/Comment 基实现提升到 kernel；本节已有 `content:*`、`term:*`、`comment:*` 别名继续作为统一 CMS 对象 Capability，本 G0 不新增按 type 别名。

## 1. 设计目的

最小化 RBAC（ADR-0008）：操作别名（Permission）+ 上下文纯函数（Policy）。起步即固化"每个操作一个别名"，敏感操作联动审计。内核提供显式 Capability 注册表；下游组件可在 API wiring 阶段登记自己的命名空间别名，但不能反向修改内核默认角色模板。

非目标：不做组织/资源级 ABAC；不做权限继承树。

## 2. 范围与依赖

- 代码位置: `inc/kernel/rbac/`
- 依赖的 kernel 组件: db, security, identity, errors
- 被谁依赖: auth（登录时装配 capabilities）, api deps（`require_capability`）, 全部 modules（仅经公开注册与检查接口）
- 外部依赖: 无新增

## 3. 领域模型

- **Permission**：`alias`（如 `content:create`）+ description。别名注册即契约：代码中使用的每个别名必须在 permissions 表 seed 与本文件第 6 节清单中存在。
- **Role**：命名角色，绑定多个 Permission。
- **Policy**：`Callable[[Principal, PolicyContext], bool]` 纯函数，按别名登记；`PolicyContext`（Pydantic）含 `resource_owner_id: UUID | None` 与 `target: dict[str, str] | None` 等通用槽。无 Policy 登记的别名 = 只要角色授予即可。
- **CapabilityChecker**：`check(principal, alias, context=None) -> bool`：匿名主体恒 False（除显式 public 端点不走此检查）；`is_system_bot` 恒 True。
- **CapabilityRegistry**：进程级显式注册表。内核先登记 canonical Capability；下游代码再经公开函数登记自身 `CapabilityDefinition`；API 组合根校验后冻结，运行期禁止继续修改。
- FastAPI 依赖 `require_capability(alias, context_loader=None)`：失败抛 RBAC_001。

## 4. 状态机

无。

## 5. 数据库

### 表: `roles`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| name | str(32) | unique, not null | reader/member/editor/moderator/admin/system-bot |
| description | str(256) | null | |
| created_at | timestamptz | not null | |

### 表: `permissions`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| alias | str(64) | unique, not null | 操作别名 |
| description | str(256) | null | |
| created_at | timestamptz | not null | |

### 表: `role_permissions`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| role_id | uuid | FK roles.id | 联合主键 |
| permission_id | uuid | FK permissions.id | 联合主键 |

### 表: `user_roles`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| user_id | uuid | FK users.id | 联合主键 |
| role_id | uuid | FK roles.id | 联合主键 |
| organization_id | uuid | null | 预留（本期恒 null） |

## 6. Capability 别名登记处（权威清单）

内核别名：

| 别名 | Policy | 说明 | 审计 |
|---|---|---|---|
| user:read_any | — | 管理端读任意用户 | 否 |
| user:update_any | — | 管理端改任意用户 | 是 |
| user:ban | — | 封禁/解封 | 是 |
| role:manage | — | 角色与权限点管理 | 是 |
| role:assign | — | 给用户授角色 | 是 |
| audit:read | — | 查审计日志 | 否 |
| setting:read | — | 读设置 | 否 |
| setting:update | — | 改设置 | 是 |
| task:manage | — | 查看/干预任务实例 | 否 |

CMS 对象别名（登记于此表与 kernel 对象规格双处，保持一致）：

| 别名 | Policy | 说明 | 审计 |
|---|---|---|---|
| content:create | — | 创建内容 | 否 |
| content:update_own | owner 匹配 | 改自己的内容 | 否 |
| content:update_any | — | 改任意内容 | 是 |
| content:delete_own | owner 匹配 | 删自己的内容 | 否 |
| content:delete_any | — | 删任意内容 | 是 |
| content:publish | owner 匹配或 update_any | 发布/下架 | 否 |
| term:manage | — | term 增删改 | 否 |
| term:assign | — | 给内容挂 term | 否 |
| comment:create | — | 发评论 | 否 |
| comment:update_own | owner 匹配 | 改自己的评论 | 否 |
| comment:delete_own | owner 匹配 | 删自己的评论 | 否 |
| comment:delete_any | — | 删任意评论 | 是 |
| comment:moderate | — | 审核评论 | 是 |

默认角色授予（seed）：

| 角色 | 别名 |
|---|---|
| admin | 全部 |
| moderator | comment:moderate, comment:delete_any, content:update_any, content:delete_any |
| editor | content:create/update_own/delete_own/publish, term:manage, term:assign |
| member | content:create/update_own/delete_own, term:assign, comment:create/update_own/delete_own |
| reader | comment:create/update_own/delete_own |
| system-bot | 内部任务声明注入（不经表） |

### 下游 Capability 显式登记契约

- 下游组件只登记 `CapabilityDefinition(alias, description, policy, audited)`，不得直接修改 `CORE_CAPABILITIES`、`MODULE_CAPABILITIES`、`ALL_CAPABILITIES` 或 `ROLE_SEEDS`。
- 公开入口为 `register_capability(definition)` / `register_capabilities(*definitions)`；调用方由 `inc/api/wiring.py` 显式导入和调用，禁止自动发现、目录扫描和 import 副作用登记。
- alias 使用稳定的 `namespace:operation` 形式，长度不超过 64；同名、非法格式、空描述以及注册表冻结后的登记均 fail-fast。
- `seed_rbac` 默认同步注册表当前快照中的 Permission；只创建缺失 Permission，并继续严格使用既有 `ROLE_SEEDS` 建立 canonical 角色关系。下游新增 Capability 不自动授予 admin 或任何现有角色。
- 本契约只开放 Capability 登记，不开放下游默认角色登记、动态角色 CRUD、按模块自动授权或资源级 scope。

### HTTP API（管理端）

| 方法 | 路径 | Capability | 请求 DTO | 响应 DTO | 说明 |
|---|---|---|---|---|---|
| GET | /api/v1/roles | role:manage | — | list[RoleRead] | |
| GET | /api/v1/permissions | role:manage | — | list[PermissionRead] | |
| POST | /api/v1/users/{id}/roles | role:assign | RoleAssign | UserRead | 触发 `role.assigned` |

## 7. Pipeline

无。

## 8. Event

- 发布: `role.assigned`（payload `{user_id, role, actor_id}`），由显式 wiring 订阅审计。
- 订阅: 无（登录时实时装配 capabilities，不依赖事件同步）。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| RBAC_001 | 403 | 缺少能力别名 | check 失败 |
| RBAC_002 | 404 | 角色不存在 | 授角色时 |
| RBAC_003 | 500 | 别名未登记 | 启动校验发现代码用了未登记别名（fail-fast） |

## 10. Cron / 任务

无。

## 11. 测试边界

- 未登记别名出现在 `require_capability` → 启动校验失败（RBAC_003）。
- owner Policy：`resource_owner_id == principal.id` 通过；不一致拒绝；moderator 持 update_any 绕过 own 限制。
- 匿名主体任何别名检查 False；system-bot 恒 True。
- 授角色后重新登录，Principal.capabilities 含新别名（不缓存旧快照）。
- seed 幂等：重复执行不产生重复行。
- 下游 Capability 经公开入口登记后可被 checker/dependency 使用，并能由 `seed_rbac` 写入缺失 Permission；不改变任何 canonical 角色的权限集合。
- duplicate/非法 alias、空描述和冻结后登记均在启动阶段失败；测试重置注册表后恢复可登记状态。

## 12. 未决事项

- organization_id 维度的启用（配合 organizations 占位表，后期 ADR）。
- capabilities 快照缓存（登录实时装配成本可接受，暂不缓存）。
- 下游模块若未来需要默认角色模板、资源 scope 或后台动态角色管理，另写规格与 ADR；本期不从 Capability 登记隐式推导角色。

## 13. 实现边界（M1.6）

- ORM 与 UoW 位于 `inc/kernel/rbac/`；消费者只依赖 `RoleRead`、`PermissionRead`、`RoleAssign`、`Principal`、`CapabilityChecker` 和 `require_capability`。
- `0003_rbac` 迁移创建四张表并写入 canonical permission/role seed；运行时 `seed_rbac` 可安全重复执行。
- `role_permissions`、`user_roles` 为联合主键关联表，是 ADR-0019 对全局 UUID 聚合主键约定的明确例外。
- 未登记 alias 在依赖构造或 checker 查询时抛 `RBAC_003`；应用启动 wiring 应调用 `validate_capability_registry(ALL_CAPABILITY_ALIASES)`。
- `CapabilityRegistry` 暴露有序定义快照并支持冻结；API wiring 完成全部显式登记与校验后冻结注册表。
- `seed_rbac` 的 Permission 输入默认为注册表快照，`ROLE_SEEDS` 及其既有 alias 分配保持不变。
