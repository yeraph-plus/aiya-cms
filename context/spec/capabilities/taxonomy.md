# Taxonomy Capability 规格

## 1. 职责

taxonomy 提供可由 feature 声明的平面多维标签。category 是一个维度配置，不是独立模型；不实现父子分类、树路径、递归查询或 WordPress taxonomy 兼容。

taxonomy 可以标记 content 等任意 target，但不导入目标 capability，也不建立跨能力外键。

community tag 不属于 taxonomy term，也不以 opaque assignment 关联 discussion；其层级、数量约束、关联表和查询归 [`community.md`](community.md)，两者不得双写或共享 ID。

## 2. DimensionSpec

feature 注册：

- 稳定 `dimension_key`、显示名称、版本。
- 允许的 target types。
- `selection_mode=single|multiple`。
- `min_items`、`max_items`。
- term slug/name/metadata schema。
- 查询组合：同维度 OR，跨维度 AND。
- 管理权限和公开可见性。

post 初始注册：

- `category`：single，默认最多 1 项。
- `tag`：multiple，最大数量由 post feature 明确配置。

page 不注册任何 dimension。

## 3. 表所有权

- `taxonomy_dimensions`：dimension key、spec version、状态和非执行型展示元数据。
- `taxonomy_terms`：dimension key、name、slug、description、metadata、状态和时间。
- `taxonomy_assignments`：dimension key、term_id、target_type、target_id、position 和时间。

DimensionSpec 是代码事实来源；表中 dimension row 由 migration/显式部署同步维护，用于约束和审计，不在普通启动或读取时自动写入。

assignment 的 target 是 opaque reference。term -> dimension 为 taxonomy 内部约束；target_id 不建外键。

## 4. Commands

- `CreateTerm`、`UpdateTerm`、`ArchiveTerm`。
- `AssignTerms`：按 dimension 替换一个 target 的 term 集合。
- `RemoveTargetAssignments`：由明确删除 workflow 调用。
- 运维 `SyncDimensionDefinitions`：仅迁移/ops 使用，dry-run 后同步代码声明版本。

所有 Command 校验 dimension、target type、TargetExists Port、选择数量、term 状态和权限。未知维度不得自动创建。

## 5. Queries

- `ListDimensions` 从 frozen registry 与持久元数据生成 DTO。
- `ListTerms`、`GetTargetTerms`。
- `FindTargetsByTerms` 返回 opaque target IDs，供 feature 再调用目标 capability Query。
- 同维度所选 term 为 OR，多个维度之间为 AND。
- 列表排序必须稳定；term 默认按 position/name/id。

taxonomy 不提供跨 content 表的 join 或分页 total。需要按标签分页内容时，由 feature 使用专用只读 Port/投影，且不得破坏能力表所有权。

## 6. 删除与孤儿

- term 默认 archive；有 assignment 时禁止物理删除。
- target 删除不会通过数据库 cascade 删除 assignment。
- 所属 feature 的删除/清理 workflow 显式调用 `RemoveTargetAssignments`。
- diagnostics 使用 `TargetExists` 批量 Port 报告孤儿，不自动删除。

## 7. Events

- `taxonomy.term_created.v1`
- `taxonomy.term_updated.v1`
- `taxonomy.term_archived.v1`
- `taxonomy.assignments_replaced.v1`

assignment 事件包含 target ref、dimension 和 term ID 集合，不复制目标业务数据。

## 8. 验收

- 重复/未知 dimension 启动失败。
- single/multiple、min/max 和 target type 规则有正负测试。
- category/tag 查询符合“同维度 OR、跨维度 AND”。
- page manifest 无 dimension/assignment。
- taxonomy 不导入 content，metadata 无 content 外键。
- orphan diagnostics 只报告不修复。
