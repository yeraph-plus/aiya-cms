# Content Capability 规格

## 1. 职责

content 提供通用内容实体、类型声明、状态转换、发布调度、置顶排序和内容间单向引用。它不知道 post/page 的具体业务含义；实际 content type 由 feature 注册。

不包含 taxonomy、comments、修订、媒体库、父子页面、前端路由、SEO 渲染、点赞/浏览统计或隐式插件钩子。

## 2. ContentTypeSpec

feature 注册不可变类型声明，至少包含：

- `type_name`、版本、显示名称。
- 对应 `data` 的 Pydantic schema 和 schema version。
- 允许状态、默认状态和 transition map。
- 是否允许 schedule、pin、owner 和 references。
- slug 策略、标题/正文/摘要约束。
- 所需 access capability keys。
- 可公开查询字段和排序选项。

ContentTypeSpec 是代码规格，不保存可执行脚本。重复 type、未知状态、无起点/终点的 transition、未登记权限或 schema 冲突必须启动失败。

## 3. 表所有权

### 3.1 `contents`

固定列：

- `id`、`type_name`、`schema_version`。
- `title`、`slug`、`body`、`excerpt`。
- `status`。
- 可选 `owner_type`、`owner_id` opaque reference。
- `data` JSONB，绑定注册类型的 Pydantic schema。
- `is_pinned`、`pin_rank`。
- `publish_at`、`published_at`、`schedule_version`。
- `version` 乐观并发号。
- `created_at`、`updated_at`、`archived_at`。

约束至少包括 `(type_name, slug)` 唯一、schedule 字段与状态一致、pin rank 范围、published 状态必须有 `published_at`。

### 3.2 `content_references`

- `source_content_id`、`target_content_id` 均为 content 自有外键。
- `kind`、`position`、有 schema 的 metadata。
- `(source, target, kind)` 唯一或按 kind 规格允许重复位置。

引用是单向关系，只从 source 独立查询；不递归展开、不表达父子层级。

## 4. 基础状态

能力提供以下标准状态词汇，ContentTypeSpec 选择子集和合法转换：

- `draft`
- `pending`
- `rejected`
- `scheduled`
- `published`
- `archived`

默认建议转换：

```text
draft -> pending | scheduled | published
pending -> draft | rejected | scheduled | published
rejected -> draft
scheduled -> draft | published
published -> archived
archived -> draft
```

所有状态变化使用命名 Command 和 transition 校验；不开放通用 status PATCH。发布后编辑是否回到 draft 由类型声明明确，首版默认允许更新已发布内容但保留 published 状态和乐观版本。

## 5. Commands

- `CreateContent`
- `UpdateContent`
- `SubmitContent`
- `RejectContent`
- `ScheduleContent`
- `UnscheduleContent`
- `PublishContent`
- `ArchiveContent`
- `RestoreContentToDraft`
- `SetContentPin`
- `ReplaceContentReferences`
- 运维 `PurgeArchivedContent`

Command 必须校验类型、Pydantic data、transition、权限、owner、乐观版本和幂等键。Content capability 不因发布自动发通知、过滤关键词或奖励积分。

## 6. 定时发布

- `ScheduleContent` 设置 `status=scheduled`、UTC `publish_at` 并增加 `schedule_version`。
- Cron 只扫描到期 ID，使用 lease 或 `FOR UPDATE SKIP LOCKED` 启动 `content.publish_scheduled.v1` workflow/activity。
- 执行幂等键为 `content_id:schedule_version`。
- 发布状态和 `content.published.v1` outbox 在同一 UoW 提交。
- worker 重启后重新扫描数据库；不创建每内容一个内存 timer。
- 取消/重排会增加 schedule version，使旧任务安全失效。

## 7. 置顶与分页

默认列表排序：

```text
is_pinned DESC,
pin_rank DESC,
published_at DESC NULLS LAST,
id DESC
```

- 置顶在查询阶段排序，置顶项占用当前页容量。
- `total` 使用同一过滤条件，包含置顶项，不受 ORDER BY 影响。
- `pin_rank` 相同以 published_at/id 保证稳定顺序。
- 只返回 published 的公开列表；后台列表可按权限选择状态。
- 若未来需要独立置顶区，必须新增 `pinned_items + items + total` 契约，不能静默改变当前分页。

## 8. 引用和删除

- reference 目标必须存在且允许被引用。
- 删除 source 时可删除其 outgoing references；存在 incoming references 时拒绝物理 purge。
- 业务 API 默认只 archive，不物理删除。
- purge 是有权限、审计、可 dry-run 的运维 Command，要求先解除 incoming references。
- 不级联删除被引用内容。

## 9. Events

- `content.created.v1`
- `content.updated.v1`
- `content.submitted.v1`
- `content.scheduled.v1`
- `content.schedule_cancelled.v1`
- `content.published.v1`
- `content.archived.v1`
- `content.pin_changed.v1`

事件只包含稳定基础字段和必要变更摘要；完整 body/data 由有权限 Query 获取。GET 不产生 `content.viewed` 或任何写副作用。

## 10. 初始类型

- post feature 注册 `post`，可以声明 taxonomy 维度，但关联由 feature/taxonomy 管理。
- page feature 注册 `page`，不声明 taxonomy，不支持父子关系。
- 两者都复用 content 表、Command 和查询，不复制 ORM/Service。

## 11. Diagnostics 与验收

diagnostics 检查未知 type/schema version、非法状态组合、过期 scheduled 积压、published 缺时间、孤儿 reference 和 data schema 不匹配，且不得修复。

验收必须覆盖：

- 未注册 type、非法 transition/data/权限被拒绝。
- 并发更新通过 version 防止丢失更新。
- 重复/并发定时扫描只发布一次。
- 取消后旧 schedule task 不发布。
- 置顶分页 total、页容量和稳定顺序符合本规格。
- incoming reference 阻止 purge，archive 不受影响。
