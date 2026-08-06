# Kernel / taxonomy（声明式 Term 对象）

> 状态：G4 基实现已迁入 kernel（2026-08-06），API 组合根已在 G7 切换，G8 已删除旧模块实现。依据 ADR-0032，`context/modules/taxonomy.md` 仅保留为迁移历史。

## 1. 设计目的

提供与 Content type 同构隔离的扁平 taxonomy：Term 由 `(content_type, group, slug)` 唯一确定，内容列表可以执行同组 OR、跨组 AND 的多维筛选。group 的可用性来自 ContentType 的声明，不在 taxonomy 内复制类型定义。

非目标：不做多 type 同查、层级 term、term 别名/合并、跨类型共享 term 或全文搜索。

## 2. 范围与依赖

- 代码位置: `inc/kernel/taxonomy/`
- 依赖的 kernel 组件: db、content（只读 ContentType catalog）、rbac、events、pipeline、errors
- 被谁依赖: content、api、声明型 modules
- 外部依赖: PostgreSQL 16、SQLAlchemy 2.0 async、Pydantic v2
- 依赖纪律: 不导入 modules；不直接操作 Content Repository，以 `ContentTypeRegistry` 和公开 `ContentService.exists` 协议校验范围

## 3. 领域模型

- **TaxonomyGroupDef**：由 ContentType 声明的 `slug/title/description`，本期 group 扁平。
- **Term**：`content_type + group + slug` 三元唯一，包含展示 name 和 TermData。
- **TermRelationship**：`content_id ↔ term_id` 多对多，无 content 外键，关联完整性由 Service/事件维护。
- **ContentTypeCatalog**：只读查询 type 是否登记、group 是否声明；taxonomy 不拥有该注册表。

## 4. 状态机

无。Term 创建即生效；删除为物理删除并级联清理 term_relationships。

## 5. 数据库

### 表: `terms`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | UUIDv7 |
| content_type | str(32) | not null, index | ContentType 隔离键 |
| group | str(32) | not null | 声明的 group slug |
| slug | str(128) | not null | group 内稳定键 |
| name | str(128) | not null | 展示名 |
| data | jsonb | not null, default `{}` | `TermData` |
| created_at / updated_at | timestamptz | not null | |

索引: `uq_terms_type_group_slug` unique(content_type, group, slug)；按 type/group/name 的查询索引按实测添加。

JSONB 字段对应的 Pydantic Model: `TermData`（`inc/kernel/taxonomy/schemas.py`）。

### 表: `term_relationships`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| content_id | uuid | 联合主键 | 不设跨对象 FK |
| term_id | uuid | 联合主键，FK terms.id on delete cascade | |

索引: `ix_term_rel_term(term_id, content_id)`；按 content 批量读取使用联合主键路径。

## 6. 公开 API（kernel 内部接口）

```python
class TermService:
    async def list(self, type_name: str, query: TermListQuery) -> Page[TermRead]: ...
    async def get(self, type_name: str, term_id: UUID) -> TermRead: ...
    async def create(self, type_name: str, dto: TermCreate, principal) -> TermRead: ...
    async def update(self, type_name: str, term_id: UUID, dto: TermUpdate, principal) -> TermRead: ...
    async def delete(self, type_name: str, term_id: UUID, principal) -> None: ...
    async def assign(self, type_name: str, content_id: UUID, dto: TermAssign, principal) -> list[TermRead]: ...
    async def terms_for_contents(self, content_ids: Sequence[UUID]) -> dict[UUID, ContentTerms]: ...
    async def content_ids_for_filter(self, type_name: str, expression: str) -> list[UUID]: ...
```

Service 只接收/返回 Pydantic DTO；`TermData` 通过 Pydantic Model 整体读写；不接收 Session。

### HTTP API（由 api 组合根提供）

| 方法 | 路径 | Capability | 请求 DTO | 响应 DTO | 说明 |
|---|---|---|---|---|---|
| GET | `/api/v1/terms/{type_name}` | 公开 | `TermListQuery` | `Page[TermRead]` | 先校验 type，再查询 |
| GET | `/api/v1/terms/{type_name}/{id}` | 公开 | — | `TermRead` | type 必须匹配 |
| POST | `/api/v1/terms/{type_name}` | `term:manage` | `TermCreate` | `TermRead` | group 必须声明 |
| PATCH | `/api/v1/terms/{type_name}/{id}` | `term:manage` | `TermUpdate` | `TermRead` | type/group 必须匹配 |
| DELETE | `/api/v1/terms/{type_name}/{id}` | `term:manage` | — | 204 | 清理关系 |
| PUT | `/api/v1/contents/{type_name}/{id}/terms` | `term:assign` | `TermAssign` | `list[TermRead]` | 全量替换关联 |

`TermListQuery` 支持 page/size/q/group/slug/date ranges/sort/order；条件 AND，q 在 name/slug 内 OR，sort 白名单追加 id。

## 7. Pipeline

- 拥有的 Pipeline key: `term.create`、`term.update`、`term.delete`、`term.assign`
- 注入点: 各写管道 before/after；向 Content 注入 `content.list.before`、`content.read.after`、`content.list.after`
- 已登记 step/槽位:
  - `content.term_filter`：解析 `group:slug` 表达式，返回 content id 集合
  - `content.terms`：为单条/批量 Content 注入 term 摘要
  - `term.assign` before：校验 content 存在/type 和 term 所属 type

## 8. Event

- 发布: `term.created`、`term.updated`、`term.deleted`、`term.assigned`，payload 包含 term/content/type/group/actor 信息。
- 订阅: `content.deleted` → 物理清理该 content 的 term_relationships；不订阅 `content.trashed`。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| TERM_001 | 404 | term 不存在 | id 不存在或 type 不匹配 |
| TERM_002 | 422 | group 未声明 | type 已知但 group 不在声明中 |
| TERM_003 | 409 | term slug 冲突 | 三元唯一冲突 |
| TERM_004 | 422 | term/content 不匹配 | assign 包含他 type term 或内容不存在 |
| TERM_005 | 404 | 内容类型未登记 | `/terms/{type_name}` scope 无效 |

## 10. Cron / 任务

无。term orphan 由 `content.deleted` 事件即时清理；无法投递时由后续内容关联修复任务兜底。

## 11. 测试边界

- 未登记 type 的列表、详情和写操作先返回 TERM_005；未知 group 返回 TERM_002。
- `(content_type, group, slug)` 三元唯一；不同 type 可使用相同 group/slug。
- assign 校验 content type、term type 和全量替换语义。
- `group:a,group:b,tag:x` 解释为同组 OR、跨组 AND；空/ malformed expression 返回校验错误。
- URL type_name 固定单一 scope；id 不能跨 type 命中。
- 列表分页、q、日期、排序和 id tie-breaker 遵循 ADR-0030。
- content.deleted 后关系清零；content.trashed/restored 不清理关系。
- `TermData` JSONB 通过 Pydantic Model 整体读写，禁止 Service 手写 dict。

## 12. 未决事项

- parent_id 层级 term、别名/合并和 group-specific TermData 另行 ADR。
