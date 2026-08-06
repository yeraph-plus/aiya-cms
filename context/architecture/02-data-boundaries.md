# 数据边界（02-data-boundaries）

本文定义数据在 ORM / DTO / JSONB 三层之间流动的硬性边界。所有规则均有架构守护测试。

## 1. 总规则

| # | 规则 | 守护 |
|---|---|---|
| 1 | Repository 返回 **ORM Model**，不返回 DTO | 代码评审 + 类型标注检查 |
| 2 | Service 入参/出参**必须是 Pydantic DTO** | mypy + 评审 |
| 3 | DTO↔ORM 转换只发生在 Service 边界（`Model.model_validate(orm, from_attributes=True)` / 显式构造 ORM 对象） | mypy |
| 4 | 所有 JSON 列一律 **JSONB**（`sqlalchemy.dialects.postgresql.JSONB`），禁止 `JSON`/`TEXT` 存 JSON | 架构测试扫描 models |
| 5 | 每个 JSONB 字段在 Python 侧**必有对应 Pydantic Model**，并在 `schemas.py` 登记 | 架构测试 |
| 6 | Service 中**禁止手写 dict 操作** JSONB 数据（`data["x"] = y`、`data.get(...)`）——一律经 Model 读写再整体赋值 | 架构测试（AST 扫描 services.py 中对 jsonb 字段的下标访问） |
| 7 | api 层只接触 DTO，不接触 ORM Model | mypy + 评审 |
| 8 | 禁止裸 SQL（`text()` 禁用，Alembic 迁移文件除外） | 架构测试 |

## 2. JSONB + Pydantic 模式

### 2.1 动机

JSONB 取代 WP postmeta 的 EAV 反模式：半结构化扩展字段进 JSONB（可索引、可 `@>` 查询），但**代码层必须强类型**——DB 层灵活不等于代码层松散。

### 2.2 登记方式

每个含 JSONB 列的组件在自身 `schemas.py` 定义稳定的边界 Model，并通过 `JsonBModel` 绑定。具体类型的动态约束由登记解释器在 Service 边界执行，不让 ORM 列类型随运行期注册项变化：

```python
# 示意（文档用，非实现代码）
class ContentDataValues(RootModel[dict[str, str]]):
    pass

class Content(Base):
    data: Mapped[ContentDataValues] = mapped_column(
        JsonBModel(ContentDataValues), ...
    )

class MovieContentType(ContentType):
    fields = (
        ContentField(slug="cover", input_type="url"),
        ContentField(slug="imdb", input_type="number"),
    )
```

- 自定义 TypeDecorator `JsonBModel` 负责 JSONB↔Pydantic 的双向校验序列化，定义在 `kernel/db/types.py`，全系统唯一入口。
- 读出来的 `orm.data` 必须是对应 Pydantic Model；写入时赋 Model 实例。Service 不得通过下标或 `.get()` 手写 JSONB。
- ADR-0032 规定 Content data 的声明键、字符串值和 unknown-key 拒绝语义；Term/Comment 继续使用各自登记的 Pydantic 边界 Model。

### 2.3 data 字段纪律（Content / Term / Comment 的 data）

- `data` 是**该类型注册时绑定的扩展字段集**，不是万能口袋。通用数据（浏览量、评分、评论数、状态）必须是真实列或视图，禁止塞进 data。
- data 的查询能力**刻意限制为简单查询**：等值匹配与 `@>` 包含。**禁止**把 data 字段纳入多级组合筛选、排序、聚合。有多维筛选需求 → 用 taxonomy；有搜索需求 → 后期 Meilisearch。
- ContentField 不提供默认值：新增可选字段时旧行保持缺失；新增 required 字段或修改规范化规则必须先迁移数据。Term/Comment schema 演进同样需要 Pydantic 校验和必要的数据迁移。

## 3. 声明解释器约定

Content 的运行期类型由不可变声明和解释器绑定，ORM 与 Service 使用统一 Pydantic 边界 Model：

```python
# 示意（文档用，非实现代码）
class ContentType(ABC):
    type_name: ClassVar[str]
    fields: ClassVar[tuple[ContentField, ...]]

class ContentTypeInterpreter:
    def validate_data(self, type_name: str, value: object) -> ContentDataValues: ...
```

- 声明类只负责元数据；Interpreter 是类型、required、constraint、validator 和字符串规范化的唯一执行边界。
- 编译后的 ContentTypeDefinition 和注册表冻结后不可修改；modules 不得绕开解释器直接写 data。
- Repository 仍使用 `Repository[ModelT]` 泛型绑定 ORM 类型；Pydantic、mypy 和启动 fail-fast 三层共同守护。

## 4. DTO 命名与分层约定

| 后缀 | 用途 | 例 |
|---|---|---|
| `XxxCreate` | 创建入参 | `ContentCreate` |
| `XxxUpdate` | 更新入参（全可选字段） | `ContentUpdate` |
| `XxxRead` | 查询出参（Service 返回给 api） | `ContentRead` |
| `XxxData` | JSONB 字段 Model | `MovieData` |
| `XxxEvent` / payload | 事件 payload | `ContentCreatedPayload` |
| `XxxContext` | Pipeline StepContext 的 payload / 扩展槽 DTO | `ViewerContext` |
| api 复合响应 | api 层组合多个模块 DTO | `ContentDetailResponse`（api 层定义） |

- Service 永远返回 `XxxRead` 或其列表/分页封装；分页封装 `Page[XxxRead]`（kernel 提供 `Page[T]` 泛型）。
- api 层复合响应 = import 各模块 `XxxRead` / 槽位 DTO 组合，**模块之间不因此产生 import**（api 是自由层）。

## 5. 主键与时间

- 全系统主键：**UUIDv7**（有序、索引友好、可分布式生成），Python 侧 `uuid.UUID`，DB 侧 `uuid`。
- 时间：一律 tz-aware `timestamptz`，UTC 存储；字段命名 `created_at` / `updated_at`（kernel Base mixin 提供），另有业务时间（如 `published_at`）单独声明。
- 枚举列：DB 存 str（不用 PG ENUM 类型，避免迁移痛苦），Python 侧 `StrEnum`/Pydantic Enum 约束。

## 6. 软删除与审计字段

- 内容类数据**不用软删除列**，用状态机（如 Content `status: draft/published/archived/trash`）表达生命周期——删除是状态转换而非标记位。
- `audit_logs` 是 append-only：只有 `created_at`，永不 UPDATE。
- 其余表默认带 `created_at` / `updated_at`。
