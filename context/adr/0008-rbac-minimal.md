# ADR-0008: 最小化 RBAC——Permission 别名 + Policy

- 状态: accepted
- 日期: 2026-08-02
- 决策者: 项目所有者 + AI 协作
- 关联: [kernel/rbac.md](../kernel/rbac.md)、[kernel/identity.md](../kernel/identity.md)

## 背景

系统需要权限控制，但面向场景是内容站点（下载站/图库/博客/轻社区）而非 ERP 级合规控制。目标是预防 bug 与信息泄漏类意外，过细的权限模型没有意义。参照 WP 的 Capability 设计：登记"用户操作 + 上下文"。

## 决策

1. **最小 RBAC**：`Role ↔ Permission` 多对多，`User ↔ Role` 多对多。Permission 即**操作别名**（如 `content:create`、`comment:moderate`），起步阶段就为每个操作起别名并固化。
2. **Policy**：上下文相关的判断（如"只能改自己的内容"）表达为纯函数 `(principal, context) -> bool`，按别名登记（如 `content:update_own` 的 Policy 校验 `resource.owner_id == principal.id`）。Permission 解决"能不能做这类事"，Policy 解决"能不能对这个对象做"。
3. **别名即契约**：每个 Capability 别名必须登记（permissions 表 + 对应文档），敏感操作执行时同时触发审计事件。未登记的别名在启动校验时 fail-fast。
4. 主体抽象 `Principal`（id、roles、capabilities 快照、是否系统 bot），由 kernel/security 在请求进入时构造，下游不直接查权限表。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| ABAC / ReBAC（完整属性/关系权限） | 表达力最强 | 复杂度远超场景需求 | 明确"更细节的设计没有意义" |
| 仅角色硬编码（if user.role == "admin"） | 零抽象 | 权限点散落代码各处，无法审计 | 与"别名固化 + 审计"目标冲突 |
| WP 式 meta cap 动态映射 | 灵活 | 字符串隐式映射，与全局反字符串约定冲突 | 用显式 Policy 登记替代 |

## 后果

### 正面
- 权限点全集可从 permissions 表与文档直接读出，天然是审计与测试清单。
- Policy 为纯函数，单测无需数据库。

### 负面 / 代价
- 每加一个操作要同时登记别名、Policy（如涉及上下文）、文档——有仪式感成本（这正是目的）。

### 逃生门
- 后期需要组织级/资源级细粒度控制时，在 Policy context 中扩展维度（organizations 表已占位），别名体系不变。
