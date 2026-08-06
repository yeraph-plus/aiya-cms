# ADR-0009: JSONB 纪律——必有 Pydantic Model、仅简单查询

- 状态: accepted
- 日期: 2026-08-02
- 决策者: 项目所有者 + AI 协作
- 关联: [architecture/02-data-boundaries.md](../architecture/02-data-boundaries.md)、ADR-0032

> ADR-0032 将 Content data 的运行期绑定细化为声明键 + `ContentDataValues(RootModel[dict[str, str]])`；仍满足本 ADR 的 Pydantic Model、禁手写 dict 和查询白名单纪律。

## 背景

WP 的 postmeta 是 EAV 反模式（行转列、查询灾难）。现代 PG 的 JSONB 可以承载半结构化扩展，但若无约束，JSONB 会退化成"万能字段"：筛选、排序、业务规则全钻进 JSON 文档，维护困难。需要在"灵活扩展"与"结构纪律"之间划线。

## 决策

1. 所有 JSON 列一律 **JSONB**；每个 JSONB 字段在 Python 侧**必有对应 Pydantic Model**，经 kernel 的统一 TypeDecorator（`JsonBModel`）双向校验序列化。
2. **Service 禁止手写 dict 操作** JSONB 数据；读写一律经 Model。
3. JSONB 查询能力**白名单制**：仅允许等值匹配与 `@>` 包含；禁止 JSONB 字段参与多级组合筛选、排序、聚合。需要多维筛选 → taxonomy；需要全文/复杂搜索 → 后期 Meilisearch（预留适配位）。
4. 通用数据（浏览量、评分、状态、计数）必须是真实列或 `to_jsonb` 组合视图，禁止进 `data`。
5. `data` 的 Schema 由内容类型注册时绑定。ADR-0032 后 ContentField 不提供默认值：新增可选字段保持缺失；新增 required 字段、修改规范化规则或其他破坏性变更必须走数据迁移 + ADR。
6. 守护：架构测试校验"JSONB 列必有登记 Model"、"services.py 无 jsonb 下标访问"。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| EAV（WP postmeta 式） | 终极灵活 | 行转列、查询与索引灾难 | 所有者明确反对 |
| JSONB 自由查询（开放 jsonb 路径筛选/排序） | 功能强 | 查询契约失控、索引无法设计、性能不可预测 | 违反纪律第 3 条的目的 |
| 全部结构化列（禁用 JSONB） | 最严格 | 每加字段都要迁移，内容类型扩展成本高 | 失去类型注册机制的灵活性 |

## 后果

### 正面
- data 字段既能承载"电影有 IMDB 评分、图集有 EXIF"这类差异，又不会失控成查询黑洞。
- Schema 注册制让"这个 type 的 data 有什么字段"永远有代码级答案。

### 负面 / 代价
- 某些"顺手从 data 里筛一下"的需求被拒绝，必须走 taxonomy 或真实列——短期多一步设计。

### 逃生门
- 确需 JSONB 复杂查询的个案：提 ADR 开白名单例外，并为该路径建对应 GIN 索引。
