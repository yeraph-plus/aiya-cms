# Module / taxonomy

> Status: archived after G8 (2026-08-06). The implementation was removed; the authoritative specification is [kernel/taxonomy.md](../kernel/taxonomy.md). This file is migration history only.

> 状态：M2 当前实现/迁移基线。目标设计已由 ADR-0032 冻结为 `inc/kernel/taxonomy`，现有表与查询语义作为迁移输入；实施时由新的 kernel 规格替代并删除旧实现。

## 1. 设计目的

多维分类/标签体系：term 按 `content_type` 隔离（不同类型互不可见，杜绝污染），同类型内按 `group` 分维度（category/artist/tags/series，随内容类型注册时配置）。为内容列表提供多维筛选能力。

非目标：不做层级 term（树形分类后期需要再加 parent_id，本期扁平）；不做跨类型共享 term。

## 2. 范围与依赖

- 代码位置: `inc/modules/taxonomy/`
- 依赖: kernel 的 db / rbac / events / pipeline / errors
- 被谁依赖: 仅 api 层
- 内部结构: 标准模块结构

## 3. 领域模型

- **Term**：`(content_type, group, slug)` 三元唯一；`name` 展示；`data` 扩展（如封面图）。
- **TermRelationship**：`content_id ↔ term_id` 多对多。
- **分组配置对齐**：内容类型注册时声明 `term_groups`（content.md）；term 创建时校验该 type+group 已声明，否则 TERM_002。taxonomy 不知道 content 的类型注册表——**由 api 层 wiring 把 content 模块的"类型-分组校验函数"以 step 注入 taxonomy 的校验管道**（跨模块协作的标准姿势；字符串 key 对齐 + 启动校验）。

## 4. 状态机

无（term 无生命周期；删除即物理删除并清关联）。

## 5. 数据库

### 表: `terms`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| content_type | str(32) | not null | 隔离键 |
| group | str(32) | not null | 维度：category/artist/tags/series… |
| slug | str(128) | not null | |
| name | str(128) | not null | |
| data | jsonb | not null, default {} | → TermData |
| created_at / updated_at | timestamptz | not null | |

索引: `uq_terms_type_group_slug` unique(content_type, group, slug)

### 表: `term_relationships`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| content_id | uuid | not null | 联合主键；无 FK（content 属另一模块，靠 Service 校验） |
| term_id | uuid | FK terms.id, on delete cascade | 联合主键 |

索引: `ix_term_rel_term(term_id, content_id)`（多维筛选主路径）

JSONB Pydantic Model: `TermData{description: str | None, image_url: str | None}`（基础集；各 group 不单独建模，扩展经 ADR）。

## 6. HTTP API

| 方法 | 路径 | Capability | 请求 DTO | 响应 DTO | 说明 |
|---|---|---|---|---|---|
| GET | /api/v1/terms/{type_name} | 公开 | `TermListQuery`: page/size/q/group/slug/date ranges/sort/order | Page[TermRead] | 类型先校验，再按 URL type_name 隔离 |
| GET | /api/v1/terms/{type_name}/{id} | 公开 | — | TermRead | 类型由 URL 识别 |
| POST | /api/v1/terms/{type_name} | term:manage | TermCreate | TermRead | 类型由 URL 识别 |
| PATCH | /api/v1/terms/{type_name}/{id} | term:manage | TermUpdate | TermRead | 类型由 URL 识别 |
| DELETE | /api/v1/terms/{type_name}/{id} | term:manage | — | 204 | 级联清关联 |
| PUT | /api/v1/contents/{type_name}/{id}/terms | term:assign + 内容归属校验 | TermAssign{term_ids} | list[TermRead] | 全量替换式挂载 |

## 7. Pipeline

| key | kind | 说明 |
|---|---|---|
| term.create | write | before：类型+分组校验槽位（content 提供校验 step） |
| term.update | write | |
| term.delete | write | after：发 term.deleted |
| term.assign | write | before：content 存在性与归属校验槽位；after：发 term.assigned |

- 向 content 注入的 step（经 api wiring）：
  - `content.list.before` → 解析 `terms` 筛选参数为 term id 集合（供 content 列表查询使用；槽位常量 `SLOT_TERM_FILTER`，语义由 taxonomy resolver 定义）。
  - `content.read.after` / `content.list.after` → 注入每条内容的 term 摘要（槽位 `SLOT_CONTENT_TERMS` + `ContentTermsDTO`，列表批量查询防 N+1）。

## 8. Event

- 发布: `term.created` / `term.updated` / `term.deleted` `{term_id, content_type, group}`、`term.assigned` `{content_id, term_ids, actor_id}`。
- 订阅: `content.deleted` → 清理该 content 的全部 term_relationships（跨模块写入的标准范例）。

## 9. Service 泛型签名

无泛型（TermData 单一 Model）：

```python
class TermService(Protocol):
    async def list(self, type_name: str, query: TermListQuery) -> Page[TermRead]
    async def get(self, type_name: str, id: UUID) -> TermRead
    async def create(self, type_name: str, dto: TermCreate, principal) -> TermRead
    async def update(self, type_name: str, id: UUID, dto: TermUpdate, principal) -> TermRead
    async def delete(self, type_name: str, id: UUID, principal) -> None
    async def assign(self, type_name: str, content_id: UUID, term_ids: list[UUID], principal) -> list[TermRead]
```

## 10. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| TERM_001 | 404 | term 不存在 | |
| TERM_002 | 422 | 该内容类型未声明此分组 | create 校验 |
| TERM_003 | 409 | 三元组 slug 冲突 | |
| TERM_004 | 422 | term 与内容类型不匹配 | assign 时 term.content_type != 内容 type |
| TERM_005 | 404 | 内容类型未登记 | `/terms/{type_name}` 及其相关操作的 type_name 未注册 |

## 11. Cron / 任务

无（孤儿关联由 `content.deleted` 监听即时清理，无需定期任务）。

## 12. 测试边界

- 三元唯一冲突 → TERM_003；不同 content_type 下同 group+slug 允许（隔离语义）。
- 未声明 group → TERM_002（content 校验 step 未装配时启动校验应失败——wiring 完整性）。
- assign：含他类型 term → TERM_004；全量替换语义（先清后挂）。
- content.deleted 事件后关联行清零（跨模块写入经事件，测试 wait_idle 断言）。
- 未登记 type_name 的列表、详情及写操作先返回 taxonomy 404；已登记类型下未声明 group 返回 TERM_002。
- taxonomy 列表返回 Page[TermRead]，query 条件之间为 AND，q 在 name/slug 内为 OR。
- 列表筛选注入：`?terms=category:foo,tags:bar` 经 SLOT_TERM_FILTER 生效，同组 OR、跨组 AND（语义由 taxonomy resolver 固定）；URL type_name 固定单一内容类型，不设计多 type 同查。
- 删除 term 级联清关联。

## 13. 未决事项

- 层级 term（parent_id）：图库站如果需要多级分类再 ADR。
- term 别名/合并工具：运营需求出现时再议。
