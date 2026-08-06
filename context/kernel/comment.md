# Kernel / comment（多态评论对象）

> 状态：G5 基实现已迁入 kernel（2026-08-06），API 组合根已在 G7 切换，G8 已删除旧模块实现。comment 不读取具体内容定义，只通过目标存在性协议确认 `target_type + target_id`，策略由组合根投影注入。

## 1. 设计目的

提供所有内容类型共用的评论、审核、限频和回复树能力。评论以单表多态目标保存，目标可以是 Content 或未来其他可评论对象；回复由 parent/root/depth 表达并由 kernel 自己组树。

非目标：不实现内容类型业务字段、不直接导入 content Service、不做动态表/物理分表、不做转推引用和富文本审核。

## 2. 范围与依赖
- 评论策略由组合根通过 `TargetPolicyResolver` 显式投影；kernel 不再提供全局 target registry 或兼容注册函数。

- 代码位置: `inc/kernel/comment/`
- 依赖的 kernel 组件: db、security、rbac、events、pipeline、cache、errors
- 被谁依赖: api、content 的 comment_stats 聚合、post/forum/issue 声明、管理员审核面板
- 外部依赖: PostgreSQL 16、SQLAlchemy 2.0 async、Pydantic v2、Redis 7/Memory Cache
- 目标协议: `TargetExists = Callable[[str, UUID], bool | Awaitable[bool]]`，由 api wiring 注入

## 3. 领域模型

策略定义由组合根从内容声明投影为 `CommentTargetPolicy`；`CommentService` 只接收 `TargetPolicyResolver`，不维护全局 target registry。

- **CommentTargetDef**：`target_type`、ExtraModel、`CommentPolicy(max_depth, auto_approve, rate_limit)`。
- **Comment**：target_type/target_id、parent_id/root_id/depth、owner/status/content/data。
- **CommentThread**：顶层 Comment 加 `children`；每页先取 roots，再按 root_id 一次取后代，内存按 parent_id 组树。
- **CommentStats**：目标下 approved、未占位、含回复的评论数，供 Content.comment_count 和 detail 聚合使用。

## 4. 状态机

| 当前状态 | 事件/动作 | 下一状态 | 备注 |
|---|---|---|---|
| pending | approve | approved | `comment:moderate` |
| pending | reject | rejected | `comment:moderate` |
| approved | reject | rejected | `comment:moderate` |
| 任意 | spam | spam | `comment:moderate` |
| approved/pending | delete 且有子级 | 原 status 保留 | content=`[deleted]`，data.deleted=true |
| approved/pending | delete 且无子级 | 物理删除 | 发布 comment.deleted |

编辑不改变审核状态；parent_id 创建后不可修改，避免应用层形成循环；max_depth 是每个目标策略的硬上限。

## 5. 数据库

### 表: `comments`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | UUIDv7 |
| target_type | str(32) | not null | 注册目标类型 |
| target_id | uuid | not null | 多态目标，无外键 |
| parent_id | uuid | FK comments.id, null | 直接父评论 |
| root_id | uuid | null | 顶层 null；子级为根 id |
| depth | int | not null, default 0 | |
| owner_id | uuid | FK users.id, not null | |
| status | str(16) | not null | pending/approved/rejected/spam |
| content | text | not null | |
| data | jsonb | not null, default `{}` | `CommentExtra` |
| created_at / updated_at | timestamptz | not null | |

索引: `ix_comments_target(target_type, target_id, status, created_at, id)`；`ix_comments_root(root_id)`；`ix_comments_owner(owner_id)`。

JSONB 字段对应的 Pydantic Model: `CommentExtra`（`inc/kernel/comment/schemas.py`）。

## 6. 公开 API（kernel 内部接口）

```python
class CommentService:
    async def list_threads(self, target_type: str, target_id: UUID, query: CommentThreadQuery, principal) -> Page[CommentThread]: ...
    async def create(self, dto: CommentCreate, principal) -> CommentRead: ...
    async def update(self, comment_id: UUID, dto: CommentUpdate, principal) -> CommentRead: ...
    async def delete(self, comment_id: UUID, principal) -> None: ...
    async def moderate(self, comment_id: UUID, action: ModerateAction, principal) -> CommentRead: ...
    async def get(self, comment_id: UUID) -> CommentRead: ...
    async def stats_for_targets(self, target_type: str, target_ids: Sequence[UUID]) -> dict[UUID, CommentStats]: ...
    async def recount_target(self, target_type: str, target_id: UUID) -> int: ...
    async def purge_orphans(self, principal) -> int: ...
```

`CommentService` 只接收/返回 DTO；目标存在性由 wiring 注入，不接收 Session，不导入 ContentService。

### HTTP API（由 api 组合根提供）

| 方法 | 路径 | Capability | 请求 DTO | 响应 DTO | 说明 |
|---|---|---|---|---|---|
| GET | `/api/v1/comments` | 公开 approved | `target_type/target_id + CommentThreadQuery` | `Page[CommentThread]` | q/sort 只作用于顶层 |
| POST | `/api/v1/comments` | `comment:create` | `CommentCreate` | `CommentRead` | 目标必须存在 |
| PATCH | `/api/v1/comments/{id}` | `comment:update_own` | `CommentUpdate` | `CommentRead` | |
| DELETE | `/api/v1/comments/{id}` | `comment:delete_own/any` | — | 204 | 占位或物理删除 |
| POST | `/api/v1/comments/{id}/moderate` | `comment:moderate` | `ModerateRequest` | `CommentRead` | |
| GET | `/api/v1/comments/moderation` | `comment:moderate` | `CommentModerationQuery` | `Page[CommentRead]` | 全局审核队列 |

## 7. Pipeline

- 拥有的 Pipeline key: `comment.read`、`comment.create`、`comment.update`、`comment.delete`、`comment.moderate`
- 注入点: `comment.read.after`、`comment.create.before`、各写管道 after
- 已登记 step/槽位:
  - `comment.target_exists`：create 前验证目标存在且 type 匹配
  - `content.comment_stats`：向 Content detail/list 注入批量统计
  - `comment.read.after`：作者/interaction 扩展槽位
- 公开线程列表不是跨 target 全局搜索；moderation query 才承担全局审核列表。

## 8. Event

- 发布: `comment.created`、`comment.updated`、`comment.deleted`、`comment.moderated`，payload 包含 comment_id、target_type、target_id、owner_id、actor_id、changed_fields/动作和 `count_delta`。
- 订阅:
  - `content.deleted` → 目标下评论全部占位化并触发 comment_count 修复
  - `user.banned` → 该用户 pending 评论转 spam
- 不订阅 `content.trashed` 或 `content.restored`；内容恢复必须保留原评论。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| COMMENT_001 | 404 | 评论不存在 | id 不存在 |
| COMMENT_002 | 422 | 目标不存在/不可评论 | TargetExists 拒绝或父评论目标不一致 |
| COMMENT_003 | 422 | 超过深度上限 | depth > CommentPolicy.max_depth |
| COMMENT_004 | 429 | 频率超限 | Cache 限频触发 |
| COMMENT_005 | 409 | 状态转换非法 | moderate 动作不在状态表 |
| COMMENT_006 | 404 | target_type 未登记 | TargetPolicyResolver 无定义 |

## 10. Cron / 任务

| 名称 | 表达式 | 动作 |
|---|---|---|
| `comment.purge_orphans` | 每日 05:10 | system bot 清理目标已不存在且超过 30 天的占位评论 |

## 11. 测试边界

- target_type 未登记、目标 id 不存在、父评论跨目标和跨 type 均拒绝。
- 同一页树组装固定两次主查询；parent/root/depth 正确，超 max_depth 拒绝。
- approved/pending/rejected/spam 转换逐条覆盖；公开列表只见 approved。
- 有子评论删除变占位，无子评论物理删除；占位不计入 comment_count。
- 评论创建、审核、删除、占位、content.deleted 和 recount 均覆盖 comment_count 口径。
- 防刷 Cache key、时间窗和 system bot 行为完整覆盖。
- content.trashed/restored 不清理评论；content.deleted 清理目标评论。
- q、分页、排序、日期范围和 moderation 条件 AND/OR 语义遵循 ADR-0030。
- CommentExtra 通过 Pydantic Model 整体读写，禁止 Service 手写 JSONB dict。

## 12. 未决事项

- comment target 除 Content 外的具体对象由后续 kernel 组件登记。
- 事件可靠投递、跨进程重放和分表路由按 ADR-0010/事件 outbox 逃生门处理。
