# ADR-0033: 下游 Capability 显式登记边界

- 状态: accepted
- 日期: 2026-08-06
- 决策者: 项目维护者
- 关联: [ADR-0001](0001-layered-architecture.md)、[ADR-0008](0008-rbac-minimal.md)、[ADR-0019](0019-rbac-cache-implementation.md)、[kernel/rbac.md](../kernel/rbac.md)

## 背景

RBAC 已用 `CapabilityDefinition`、`CapabilityRegistry`、permissions 表和 `require_capability` 固化操作别名，但 canonical Capability 与 `seed_rbac` 仍直接依赖内核集中常量。未来下游组件需要新增自己的操作名时，如果必须修改内核清单，会破坏 `kernel` 不感知 `modules` 的依赖方向；如果只写入数据库，又会绕过代码注册、Policy 和启动 fail-fast。

当前没有动态角色管理、模块专属角色模板或按资源 scope 授权的强需求。本次只需打开最小且可验证的 Capability 登记入口，并保证现有内核角色模板与权限分配完全不变。

## 决策

1. 内核继续拥有并原样保留 `CORE_CAPABILITIES`、`MODULE_CAPABILITIES`、`ALL_CAPABILITIES` 与 `ROLE_SEEDS`；本 ADR 不改变任何既有 alias、角色或角色权限关系。
2. RBAC 公开 `register_capability(definition)` 与 `register_capabilities(*definitions)`。下游组件在 API 组合根的显式 wiring 阶段调用；禁止自动发现、扫描目录和依赖 import 副作用登记。
3. Capability alias 必须符合 `namespace:operation`、长度不超过数据库列上限 64；描述必须非空且不超过 256。重复、非法输入与注册表冻结后的登记立即失败。
4. `CapabilityRegistry` 提供有序定义快照并支持冻结。API 组合根完成登记和 canonical 完整性校验后冻结，运行期不可修改。
5. `seed_rbac` 默认从注册表定义快照同步缺失 Permission，但仍只使用固定的 `ROLE_SEEDS` 建立角色关系。下游 Capability 不会自动授予 admin 或其他现有角色；授权关系必须由未来明确的角色规格、迁移或管理功能决定。
6. 本次不修改 `post`、`forum`、`issue` 及 Content 的现有 Capability 使用，不新增模块角色，不增加角色管理 API，不引入资源 scope。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| 下游每次修改内核 `ALL_CAPABILITIES` | 改动最少 | kernel 感知下游操作名，集中清单持续膨胀 | 违反依赖方向和组件封装 |
| 仅向 permissions 表写字符串 | 无需进程注册 | 无 Policy、审计元数据和启动校验，checker 无法识别 | 破坏“别名即契约” |
| 自动发现模块 Capability | 接入省事 | 装配顺序不透明，失败难定位 | 违反显式注册硬约束 |
| 同时开放角色模板与动态角色管理 | 一次覆盖更多场景 | 当前没有需求，扩大授权与审计面 | 推迟到实际需求出现后单独决策 |

## 后果

### 正面

- 下游可新增独立命名空间 Capability，而无需修改 kernel 定义文件。
- 代码注册、Policy、数据库 Permission 与启动校验仍保持同一契约链。
- 现有默认角色和权限分配没有行为漂移。

### 负面 / 代价

- 新增 Capability 只完成“操作登记”，不会自动获得任何角色授权；下游必须在后续明确授权来源。
- 组合根必须维持“登记 → 校验 → 数据同步/迁移 → 冻结”的显式顺序。

### 逃生门（如适用）

- 若未来需要下游默认角色模板，可新增独立 `RoleTemplateRegistry`，不改变 Capability 注册接口。
- 若需要按资源授权，在 Policy context 或模块自有成员关系中扩展，并单独登记 ADR。
