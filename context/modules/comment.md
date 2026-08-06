# Module / comment

> Status: archived after G8 (2026-08-06). The implementation was removed; the authoritative specification is [kernel/comment.md](../kernel/comment.md). This file is migration history only.

> 状态：M2 当前实现/迁移基线。目标设计已由 ADR-0032 冻结为 `inc/kernel/comment`；ADR-0010 继续有效，实施时删除旧 modules 实现且不保留兼容层。

## 1. 设计目的

"万物皆动态"的多态评论：评论可挂任何内容类型或评论自身（回复）；单表 + root_id 两趟组树（ADR-0010）；泛型 Service 提供树构建、排序、防刷。支撑博客评论与轻社区动态。

非目标：不做动态表/分表（分表仅为上限，ADR-0010）；不做转推/引用（预留 data Model 位）；不做富文本审核（状态机预留）。

## 2. 范围与依赖

- 代码位置: `inc/modules/comment/`
- 依赖: kernel 的 db / rbac / events / pipeline / cache（防刷限频）/ errors / identity(UserRead)
- 被谁依赖: 仅 api 层
- 内部结构: 标准模块结构，含 `registry.py`（target_type 注册表）

## 3. 领域模型

- **Comment**：`target_type + target_id` 多态；`parent_id`（直接父）、`root_id`（根，顶层为 null）、`depth`；`status` 审核状态机；`data` 扩展。
- **target_type 注册**（registry.py）：`register_comment_target(target_type, data_model, policy)`——policy 含 `max_depth`（默认 3）、`auto_approve`（默认 true）、`rate_limit`（默认 10 条/10 分钟）。未注册 target_type → COMMENT_006。
- **目标存在性校验**：comment 不知道 content 的表——由 api wiring 把各属主模块的"存在性校验 step"注入 `comment.create.before`（如 content 提供校验 content 存在的 step）。未装配目标类型的校验 → 启动 fail-fast。
- **树组装**：先按 `target` 分页取顶层（root_id IS NULL），再 `root_id IN (...)` 一趟取全部后代，内存按 parent_id 挂树。每页查询恒定 2 次。

## 4. 状态机

| 当前 | 动作 | 下一 | 说明 |
|---|---|---|---|
| pending | approve | approved | comment:moderate |
| pending | reject | rejected | comment:moderate |
| approved | reject | rejected | comment:moderate |
| any | mark spam | spam | comment:moderate |
| any（own） | edit | 不变（approved/pending） | 编辑不回退状态（auto_approve 目标） |
| approved/pending | delete | （软转 trash 语义：status 保留 + 行保留） | 见下 |

删除语义：有子评论 → 内容置为占位（"已删除"），保留行维持树形；无子评论 → 物理删除。占位语义由 `data.deleted: true` 表达（CommentExtra Model 字段）。

## 5. 数据库

### 表: `comments`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| target_type | str(32) | not null | 注册键（movie/post/comment…） |
| target_id | uuid | not null | 无 FK（多态） |
| parent_id | uuid | null | FK comments.id（同表） |
| root_id | uuid | null | 顶层为 null |
| depth | int | not null, default 0 | |
| owner_id | uuid | FK users.id, not null | |
| status | str(16) | not null | pending/approved/rejected/spam |
| content | text | not null | |
| data | jsonb | not null, default {} | → 各 target_type 登记的 ExtraModel |
| created_at / updated_at | timestamptz | not null | |

索引: `ix_comments_target(target_type, target_id, status, created_at)`、`ix_comments_root(root_id)`、`ix_comments_owner(owner_id)`

JSONB Pydantic Model: 基础 `CommentExtra{edited: bool, deleted: bool, flags: list[str]}`；各 target_type 可注册子类扩展。

## 6. HTTP API

| 方法 | 路径 | Capability | 请求 DTO | 响应 DTO | 说明 |
|---|---|---|---|---|---|
| GET | /api/v1/comments?target_type=&target_id=&q=&page=&size=&sort=&order= | 公开（approved） | `CommentThreadQuery` | target-scoped 线程读取；q 匹配内容，排序只作用于顶层 |
| POST | /api/v1/comments | comment:create | CommentCreate | CommentRead | 写管道 comment.create |
| PATCH | /api/v1/comments/{id} | comment:update_own | CommentUpdate | CommentRead | |
| DELETE | /api/v1/comments/{id} | comment:delete_own/any | — | 204 | 占位/物理删除语义 |
| POST | /api/v1/comments/{id}/moderate | comment:moderate | ModerateAction | CommentRead | approve/reject/spam |

`GET /comments/moderation` 使用 `CommentModerationQuery`：status/target_type/target_id/author_id/q/created_from/created_to/updated_from/updated_to/page/size/sort/order。q 只匹配 comment.content；条件之间为 AND，排序字段为显式白名单并追加 id。

## 7. Pipeline

| key | kind | 说明 |
|---|---|---|
| comment.read | read | after：作者信息/交互数据扩展槽 |
| comment.create | write | before：目标存在性校验槽位（各属主模块注入）+ 防刷；after：发 comment.created |
| comment.update | write | after：发 comment.updated |
| comment.delete | write | after：发 comment.deleted |
| comment.moderate | write | after：发 comment.moderated |

- 向 content 注入的 step（经 api wiring）：`content.read.after` → 评论计数摘要（槽位 `SLOT_COMMENT_STATS` + `CommentStatsDTO{count}`）；`content.list.after` 同理批量。

## 8. Event

- 发布: `comment.created` `{comment_id, target_type, target_id, owner_id}`、`comment.updated`、`comment.deleted`、`comment.moderated` `{comment_id, action, actor_id}`。
- 订阅: `content.deleted` → 该内容下评论全部占位化（跨模块写入经事件）；`user.banned` → 该用户 pending 评论转 spam。

## 9. Service 泛型签名

```python
class CommentService(Generic[TExtra]):  # TExtra bound CommentExtra
    async def list_threads(self, target_type: str, target_id: UUID, query: CommentThreadQuery, principal) -> Page[CommentThread]
    async def create(self, dto: CommentCreate, principal) -> CommentRead  # 防刷+深度校验在内
    async def update(self, id: UUID, dto: CommentUpdate, principal) -> CommentRead
    async def delete(self, id: UUID, principal) -> None
    async def moderate(self, id: UUID, action: ModerateAction, principal) -> CommentRead
```

## 10. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| COMMENT_001 | 404 | 评论不存在 | |
| COMMENT_002 | 422 | 目标不存在/不可评论 | 存在性校验 step 拒绝 |
| COMMENT_003 | 422 | 超过深度上限 | depth > max_depth |
| COMMENT_004 | 429 | 频率超限 | rate_limit 触发 |
| COMMENT_005 | 409 | 状态转换非法 | moderate 非法转换 |
| COMMENT_006 | 404 | target_type 未注册 | |

## 11. Cron / 任务

- `comment.purge_orphans`（每日 05:10）：清理 target 已不存在且超 30 天的占位评论（物理删除，兜底事件漏网；系统 bot 写审计）。

## 12. 测试边界

- 未注册 target_type 发帖 → COMMENT_006；注册了但目标 id 不存在 → COMMENT_002（注入的校验 step 生效；未装配时启动失败）。
- 深度：max_depth=3 时第 4 层回复 → COMMENT_003。
- 防刷：10 分钟内第 11 条 → COMMENT_004；换用户/时间窗过后恢复（Cache 键 `aiya:comment:rl:{user}:{target}`）。
- 树组装：造 2 顶层 + 各 2 回复，断言查询次数为 2 次（SQL 计数）且树结构正确。
- 删除语义：有子 → 占位（data.deleted=true，content 不可见）；无子 → 物理删除。
- 状态机逐条转换测试；非法 → COMMENT_005。
- 公开列表仅 approved；moderator 见 pending/rejected。
- content.deleted 事件 → 该内容评论占位化（wait_idle 断言）。
- user.banned → 其 pending 评论转 spam。
- 列表 query 的分页、关键词和排序契约遵循 ADR-0030；公开线程接口不承担跨 target 的全局搜索语义。

## 13. 未决事项

- 转推/引用：`data` 中注册 QuoteModel 表达，需要时实装。
- 按内容类型同构分表：ADR-0010 上限，Repository 预留 target_type 路由参数。
- 表情反应（reaction）：归 interaction 模块（经 comment.read 注入点扩展）。
