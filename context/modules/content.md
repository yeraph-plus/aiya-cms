# Module / content

> Status: archived after G8 (2026-08-06). The implementation was removed; the authoritative specification is [kernel/content.md](../kernel/content.md). This file is migration history only.

> 状态：M2 当前实现/迁移基线。目标设计已由 ADR-0032 冻结为 `inc/kernel/content`，本目录不得继续扩展；实施时由新的 kernel 规格替代并删除旧实现，不保留兼容层。

## 1. 设计目的

类 WP Post 的内容抽象（不复刻表结构）：一张 `contents` 表 + **内容类型注册机制**，一次小型定义（data Schema + 配置）即获得新内容形态（下载资源/图集/文章…）的完整 CRUD。覆盖下载站、图库站、博客的内容主体。

非目标：不内建点赞/收藏/购买等交互（后期 interaction/commerce 模块经注入点扩展）；不做全文搜索（预留 Meilisearch）。

## 2. 范围与依赖

- 代码位置: `inc/modules/content/`
- 依赖: kernel 的 db / security(Principal) / rbac / events / pipeline / cache / errors / identity(UserRead)
- 被谁依赖: 仅 api 层
- 内部结构: 标准模块结构（见 00-modules-overview），含 `registry.py`（内容类型注册表）

## 3. 领域模型

- **Content**：`type`（注册键）区分业务形态；`status` 状态机；`data` 为该类型登记的扩展字段集；`like_count`/`rating_sum`/`rating_count`/`view_count` 等通用数据是真实列。
- **ContentType 注册**（`registry.py`）：
  ```python
  register_content_type(ContentTypeDef(
      type="movie",
      data_model=MovieData,          # Pydantic Model，约束 data
      term_groups=["category", "artist", "tags"],   # 声明可用 taxonomy 分组（taxonomy 模块对齐）
      default_status="draft",
      slug_pattern=r"^[a-z0-9-]+$",
  ))
  ```
  未注册 type 的一切操作 → CONTENT_001。注册在 wiring 期完成，运行期冻结。
- **泛型绑定**：`ContentService[TData]`；注册即得 `MovieService = ContentService[MovieData]` 形态的类型化 Service。

## 4. 状态机

| 当前 | 动作 | 下一 | Capability |
|---|---|---|---|
| draft | publish | published | content:publish |
| published | unpublish | draft | content:publish |
| published | archive | archived | content:update_own/any |
| archived | unarchive | published | content:update_own/any |
| draft/published/archived | trash | trash | content:delete_own/any |
| trash | restore | draft | content:delete_own/any |
| trash | purge | （物理删除） | content:delete_any |

非法转换 → CONTENT_004。

## 5. 数据库

### 表: `contents`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| type | str(32) | not null | 注册键 |
| title | str(256) | not null | |
| slug | str(256) | not null | |
| status | str(16) | not null, default 'draft' | |
| owner_id | uuid | FK users.id, not null | |
| content | text | not null, default '' | 正文 |
| view_count | int | not null, default 0 | 计数真实列 |
| like_count | int | not null, default 0 | 计数真实列 |
| rating_sum | int | not null, default 0 | 评分累计值 |
| rating_count | int | not null, default 0 | 评分人数 |
| data | jsonb | not null, default {} | → 各 type 登记的 DataModel |
| published_at | timestamptz | null | |
| created_at / updated_at | timestamptz | not null | |

索引: `uq_contents_type_slug` unique(type, slug)；`ix_contents_type_status(type, status, published_at desc)`；`ix_contents_owner(owner_id)`；`ix_contents_data` GIN（仅限白名单查询，ADR-0009）

JSONB Pydantic Model: 各 type 的 `XxxData`，登记于 registry；架构测试校验一致性。

## 6. HTTP API

| 方法 | 路径 | Capability | 请求 DTO | 响应 DTO | 说明 |
|---|---|---|---|---|---|
| GET | /api/v1/contents/{type_name} | 公开（仅 published） | `ContentListQuery`: page/size/q/terms/status/owner_id/date ranges/sort/order | Page[ContentRead] | 读管道 content.list；type_name 由 URL 固定隔离 |
| GET | /api/v1/contents/{type}/{slug} | 公开（published）；非公开需 content:update_own/any | — | api 复合 ContentDetailResponse | 读管道 content.read；不产生业务事件或写入 |
| POST | /api/v1/contents/{type} | content:create | ContentCreate | ContentRead | 写管道 content.create |
| PATCH | /api/v1/contents/{type}/{id} | content:update_own/any | ContentUpdate | ContentRead | 写管道 content.update |
| POST | /api/v1/contents/{type}/{id}/publish | content:publish | — | ContentRead | 状态转换 |
| POST | /api/v1/contents/{type}/{id}/unpublish | content:publish | — | ContentRead | |
| DELETE | /api/v1/contents/{type}/{id} | content:delete_own/any | — | 204 | 默认 trash；`?purge=true` 物理删除（delete_any） |

公开读仅见 published；列表条件之间为 AND，`q` 在 title/slug 内为 OR。多维筛选只走 `terms` 参数（taxonomy 提供 term 过滤，见 taxonomy.md 第 7 节协作）+ 白名单标量字段；`data` 查询仅等值/`@>` 白名单。`sort` 只能使用已登记字段，并追加 `id` 作为稳定次序。

## 7. Pipeline

拥有的 key（属主，均登记于 wiring）：

| key | kind | before 槽 | after 槽 | 说明 |
|---|---|---|---|---|
| content.list | read | 参数规整 | 列表扩展注入（批量，防 N+1） | |
| content.read | read | 权限上下文 | 详情扩展注入（viewer 上下文等） | |
| content.create | write | 校验/预处理 | 发 content.created | |
| content.update | write | 校验/预处理 | 发 content.updated | |
| content.delete | write | 级联检查 | 发 content.deleted | |

开放给其他模块的扩展槽（本模块为属主，槽位 DTO 由生产方定义）：`content.read.after` / `content.list.after`。

本模块向外部注入：无（首期）。

## 8. Event

- 发布: `content.created` `{content_id, type, owner_id}`、`content.updated` `{content_id, type, changed_fields}`、`content.published` `{content_id, type}`、`content.deleted` `{content_id, type}`。
- `content.viewed` 保留为未来显式 view Command 的登记项；GET 详情/列表不得发布该事件。计数策略需在单独规格中确定。

## 9. Service 泛型签名

```python
class ContentService(Generic[TData]):
    async def get_by_slug(self, type: str, slug: str, principal) -> ContentRead[TData]
    async def list(self, type: str, query: ContentListQuery, principal) -> Page[ContentRead[TData]]
    async def create(self, type: str, dto: ContentCreate[TData], principal) -> ContentRead[TData]
    async def update(self, id: UUID, dto: ContentUpdate[TData], principal) -> ContentRead[TData]
    async def transition(self, id: UUID, action: TransitionAction, principal) -> ContentRead[TData]
```

`ContentRead.data` 静态类型为 TData（mypy 守护）；运行期 Pydantic 校验兜底。

## 10. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| CONTENT_001 | 404 | 内容类型未注册 | 未注册 type |
| CONTENT_002 | 409 | slug 冲突 | 同 type 下 slug 重复 |
| CONTENT_003 | 404 | 内容不存在 | |
| CONTENT_004 | 409 | 状态转换非法 | 状态机外转换 |
| CONTENT_005 | 422 | data 校验失败 | 与该类型 DataModel 不符 |

## 11. Cron / 任务

- `content.purge_trash`（每日 04:50）：trash 超 30 天物理删除（系统 bot，写审计）。

## 12. 测试边界

- 未注册 type 的任何端点 → CONTENT_001。
- 列表 query 的 page/size/q/status/sort/order 组合必须保持 AND/OR 语义；q 按字面包含匹配。
- `terms=category:a,category:b,tags:x` 在单一 type_name 内解释为同组 OR、跨组 AND；不支持多 type 同查。
- 注册即得 CRUD：定义测试用 DataModel 注册后，create/read/update/list 全通且 data 类型正确。
- data 非法 → CONTENT_005；合法但多余字段 → 按 DataModel 配置拒绝（forbid extra）。
- slug 冲突 → CONTENT_002；不同 type 同 slug 允许。
- 状态机全转换表逐条测试；非法 → CONTENT_004；publish 置 published_at。
- 匿名列表仅 published；owner 见自己的 draft；moderator（update_any）见全部。
- own/any 权限：member 改他人内容 → RBAC_001；moderator 可改。
- GET 详情/列表后 `wait_idle` 不改变 `view_count`，也不新增业务事件或审计记录。
- purge Cron 只删 trash 且超龄行。
- 读路径零写：GET 详情/列表后无任何业务表变更（审计/日志无新增）。

## 13. 未决事项

- 统一列表查询与未来搜索边界见 ADR-0030；当前 `q` 仅为 SQL 简单关键词过滤，不实现 Meilisearch。
- 版本历史/修订：未规划，需要时新模块（经事件落历史表）。
- 首页聚合缓存：键 `aiya:home:*`，TTL 由具体缓存消费者或启动期 `config.Settings` 决定；不登记为运行期 settings。
