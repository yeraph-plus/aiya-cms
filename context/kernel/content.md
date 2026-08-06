# Kernel / content（声明式 Content 对象）

> 状态：G3 基实现已迁入 `inc/kernel/content/`，依据 ADR-0032；API 组合根已在 G7 切换，G8 已删除旧模块实现。

## 1. 设计目的

提供所有站点共用的 Content 对象、按 `type_name` 隔离的 CRUD/查询、状态转换、声明式类型解释和 trash 生命周期。具体类型的字段、状态、taxonomy group 和评论策略由 modules 声明，kernel 不内置 `post`、`forum`、`issue`。

非目标：不实现具体站点业务字段；不做多 type 同查；不做 JSONB 多维筛选、排序或全文搜索；不实现 interaction、SEO、版本历史和物理分表。

## 2. 范围与依赖
- 注册表只允许由组合根显式创建、注册并冻结；kernel 不再提供全局 `content_type_registry` 或兼容注册函数。

- 代码位置: `inc/kernel/content/`
- 依赖的 kernel 组件: db、security、rbac、events、pipeline、tasks、cache、errors
- 被谁依赖: taxonomy、comment、api、post/forum/issue 声明模块、interaction 事件适配器
- 外部依赖: PostgreSQL 16、SQLAlchemy 2.0 async、Pydantic v2、APScheduler 3.x
- 依赖纪律: 不导入任何 `inc.modules`；interaction/comment 的计数变化由 api wiring 通过公开方法或已登记事件适配

## 3. 领域模型

- **Content**：共享 `contents` 表中的一个对象，`type` 是注册键；固定列承载标题、正文、SEO 摘要、状态和计数，`data` 承载类型声明的扩展字段。
- **ContentType**：modules 提供的声明类；编译后成为不可变 `ContentTypeDefinition`。
- **ContentField**：`slug/title/description/input_type/required/constraints/validator`；输入类型只影响前端组件和规范化，data 最终全部存字符串。
- **ContentStatusDef**：状态 slug、公开性和可执行动作元数据。
- **ContentTransitionDef**：动作、允许起始状态、目标状态和 Capability 别名。
- **TaxonomyGroupDef**：内容类型允许使用的 taxonomy 分组元数据。
- **CommentPolicy**：目标是否允许评论、最大深度、自动审核和限频策略。
- **TrashPolicy**：保留天数；`trash` 状态由父类提供。
- **ContentDataValues**：`RootModel[dict[str, str]]`，是 `contents.data` 的唯一 Pydantic 边界模型。

解释流程：

```text
modules.ContentType 子类
    → ContentTypeInterpreter 校验/规范化
    → ContentTypeRegistry.freeze()
    → ContentService 按 type_name 执行 CRUD、状态、查询
```

## 4. 状态机

具体状态和转换由每个 ContentType 声明；以下是 kernel 固定规则：

| 当前状态 | 事件/动作 | 下一状态 | 备注 |
|---|---|---|---|
| 任意非 trash | `trash` | `trash` | 写入 `trashed_at`，发布 `content.trashed` |
| `trash` | `restore` | `default_status` | 清空 `trashed_at`，发布 `content.restored` |
| `trash` 且到期 | `purge` | 物理删除 | 仅 `content:delete_any`，发布 `content.deleted` |
| 类型声明状态 | 类型声明动作 | 类型声明目标状态 | 启动时校验 transition 合法 |

状态值与动作分离：`published` 是状态，`publish` 是动作。`trash` 不由子类重复声明。匿名读只允许声明为公开的状态；状态请求按 URL `type_name` 动态校验。

## 5. 数据库

### 表: `contents`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | UUIDv7 |
| type | str(32) | not null | ContentType 注册键 |
| title | str(256) | not null | 固定标题 |
| slug | str(256) | not null | `(type, slug)` 内唯一 |
| status | str(32) | not null | 类型状态；`trash` 为保留值 |
| owner_id | uuid | FK users.id, not null | 所有者 |
| content | text | not null, default `''` | 正文 |
| excerpt | text | not null, default `''` | 摘要/SEO 输入 |
| view_count | bigint | not null, default 0 | 交互事实聚合 |
| like_count | bigint | not null, default 0 | 交互事实聚合 |
| rating_sum | bigint | not null, default 0 | 评分累计 |
| rating_count | bigint | not null, default 0 | 评分人数 |
| comment_count | bigint | not null, default 0 | approved、未占位、含回复的评论数 |
| data | jsonb | not null, default `{}` | `ContentDataValues` |
| published_at | timestamptz | null | 进入公开状态时写入 |
| trashed_at | timestamptz | null | 进入 trash 的时间 |
| created_at / updated_at | timestamptz | not null | `updated_at` 为修改时间 |

索引:

- `uq_contents_type_slug` unique(type, slug)
- `ix_contents_type_status(type, status, published_at desc)`
- `ix_contents_owner(owner_id)`
- `ix_contents_type_updated(type, updated_at, id)`
- `ix_contents_type_comment_count(type, comment_count, id)`
- `ix_contents_data` GIN 仅用于白名单等值/`@>` 查询

JSONB 字段对应的 Pydantic Model: `ContentDataValues`（`inc/kernel/content/schemas.py`）。

## 6. 公开 API（kernel 内部接口）

```python
class ContentType(ABC): ...
class ContentTypeDefinition(frozen=True): ...
class ContentTypeInterpreter:
    def compile(self, declaration: type[ContentType]) -> ContentTypeDefinition: ...
class ContentTypeRegistry:
    def register(self, declaration: type[ContentType]) -> None: ...
    def require(self, type_name: str) -> ContentTypeDefinition: ...
    def freeze(self) -> None: ...
class ContentService:
    async def list_types(self) -> list[ContentTypeRead]: ...
    async def list(self, type_name: str, query: ContentListQuery, principal) -> Page[ContentRead]: ...
    async def get_by_slug(self, type_name: str, slug: str, principal) -> ContentRead: ...
    async def create(self, type_name: str, dto: ContentCreate, principal) -> ContentRead: ...
    async def update(self, type_name: str, content_id: UUID, dto: ContentUpdate, principal) -> ContentRead: ...
    async def transition(self, type_name: str, content_id: UUID, action: str, principal) -> ContentRead: ...
    async def exists(self, type_name: str, content_id: UUID) -> bool: ...
    async def purge_trash(self, principal) -> int: ...
    async def recount_comments(self, principal) -> int: ...
```

Service 只接收/返回 Pydantic DTO；Repository 返回 ORM Model；Service 不接收 Session。`ContentRead.status` 为 str，`ContentRead.data` 为 `dict[str, str]`。

### HTTP API（由 api 组合根提供）

| 方法 | 路径 | Capability | 请求 DTO | 响应 DTO | 说明 |
|---|---|---|---|---|---|
| GET | `/api/v1/content-types` | `content:create` 或 `content:update_any` | — | `list[ContentTypeRead]` | 返回完整类型/字段/group/query 元数据 |
| GET | `/api/v1/contents/{type_name}` | 公开 | `ContentListQuery` | `Page[ContentRead]` | type_name 固定单一范围 |
| GET | `/api/v1/contents/{type_name}/{slug}` | 公开或 `content:update_any` | — | `ContentDetailResponse` | api 聚合 terms/comments |
| POST | `/api/v1/contents/{type_name}` | `content:create` | `ContentCreate` | `ContentRead` | |
| PATCH | `/api/v1/contents/{type_name}/{id}` | `content:update_own/any` | `ContentUpdate` | `ContentRead` | |
| POST | `/api/v1/contents/{type_name}/{id}/{action}` | action 对应 Capability | — | `ContentRead` | action 按 transition 白名单校验 |
| DELETE | `/api/v1/contents/{type_name}/{id}` | `content:delete_own/any` | `purge` 可选 | 204 | 默认 trash，purge 需 any |

`ContentListQuery` 支持 page/size/q/terms/status/owner/date ranges/sort/order。`q` 匹配 title/slug/excerpt；所有独立条件 AND，多字段 q OR；sort 仅使用声明白名单并追加 id。

`comment_count` 与 `trashed_at` 属于系统维护字段：可在 `ContentRead` 返回，但 PATCH 即使出现在 `ContentUpdate` 中也不得由用户写入；服务层以 `CONTENT_005` 明确拒绝，分别由评论事件/recount 与 trash/restore transition 维护。

## 7. Pipeline

- 拥有的 Pipeline key: `content.list`、`content.read`、`content.create`、`content.update`、`content.delete`
- 注入点: `content.list.before`、`content.list.after`、`content.read.after`、各写管道 before/after
- 已登记 step/槽位:
  - `content.term_filter`：taxonomy 将 terms 表达式解析为 content id 集合
  - `content.terms`：taxonomy 注入单条/批量 term 摘要
  - `content.comment_stats`：comment 注入评论统计 DTO
  - `content.interaction`：interaction 只读聚合槽位
- 读管道禁止写库和业务事件；列表扩展必须批量查询，避免 N+1。

## 8. Event

- 发布:
  - `content.created`：`ContentCreatedPayload(content_id, type, owner_id)`
  - `content.updated`：`ContentUpdatedPayload(content_id, type, owner_id, changed_fields)`
  - `content.published`：`ContentTransitionPayload(content_id, type, action)`
  - `content.trashed`：`ContentTransitionPayload(content_id, type, action="trash")`
  - `content.restored`：`ContentTransitionPayload(content_id, type, action="restore")`
  - `content.deleted`：`ContentDeletedPayload(content_id, type, owner_id, purged=True)`，仅物理删除
- 订阅: 无直接跨业务模块订阅；api wiring 可将 `interaction.changed` 和评论计数事件适配到公开聚合方法。taxonomy/comment 监听 `content.deleted` 清理自己的关联。
- `content.viewed` 仅登记为未来显式 view Command，GET 不发布。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| CONTENT_001 | 404 | 内容类型未登记 | type_name 不存在 |
| CONTENT_002 | 409 | slug 冲突 | 同 type 下 slug 重复 |
| CONTENT_003 | 404 | 内容不存在 | id/slug 不存在或 type 不匹配 |
| CONTENT_004 | 409 | 状态转换非法 | 不在声明 transition 表 |
| CONTENT_005 | 422 | 内容数据/查询校验失败 | 未知字段、required 缺失、validator 或 query 失败 |

## 10. Cron / 任务

| 名称 | 表达式 | 动作 |
|---|---|---|
| `content.purge_trash` | 每日 04:50 | system bot 按 type retention 删除到期 trash |
| `content.recount_comments` | 每日 05:20 | system bot 按冻结口径重算 comment_count |

## 11. 测试边界

- 声明类必填项、重复/非法 type/status/field/group/action、非法 default/transition 在注册时 fail-fast。
- registry freeze 后不可追加或修改；kernel 不导入 modules；API 显式注册 post/forum/issue。
- `/content-types` 返回全部字段、状态、动作、group、评论和 query 元数据，不泄露 callback。
- Content CRUD 始终同时校验 URL type_name 和数据库 type；相同 slug 可跨 type 存在。
- data 只允许已声明键，所有值规范化为字符串；required/validator/约束失败返回 CONTENT_005。
- q、status、taxonomy、分页、日期、排序可组合；同组 OR、跨组 AND；不支持多 type。
- published_at、updated_at、excerpt、comment_count、trashed_at 的写入和查询边界完整覆盖。
- trash/restore 不清理关联；到期 purge 才发布 content.deleted，并由 Cron/重启后继续执行。
- 读接口零业务写入；sort 追加 id 后分页稳定。

## 12. 未决事项

- 具体 post/forum/issue 的业务字段和 group 组合由各模块规格冻结后登记；kernel 不提供默认业务字段。
- 计数事件可靠投递/跨进程补偿保留给后续 outbox 方案；本期用 EventBus + recount 兜底。
