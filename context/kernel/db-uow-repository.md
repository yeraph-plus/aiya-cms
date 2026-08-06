# Kernel / db（engine / Base / UoW / Repository）

## 1. 设计目的

持久化基础设施的唯一入口：异步 engine/session 管理、ORM Base 与通用 mixin、JSONB↔Pydantic 的 TypeDecorator、UoW 事务边界、Repository 基类。**Session 只允许存在于本组件与 pipeline 执行器内部**（ADR-0003）。

非目标：不做读写分离、不做分库分表。

## 2. 范围与依赖

- 代码位置: `inc/kernel/db/`
- 依赖的 kernel 组件: config, errors, logging
- 被谁依赖: identity, rbac, auth, audit, settings, tasks, mail, pipeline（执行器）, 全部 modules
- 外部依赖: sqlalchemy[asyncio] 2.0, asyncpg, alembic（迁移）

## 3. 领域模型

- **engine/session**：`create_async_engine(settings.database_url)`；`async_sessionmaker`（expire_on_commit=False）。连接获取只经 UoW。
- **Base(DeclarativeBase)** + **TimestampMixin**（`created_at`/`updated_at`，tz-aware UTC，onupdate 自动）。主键约定 `id: UUID`（UUIDv7，应用侧生成）。
- **JsonBModel(TypeDecorator)**：构造参数为 Pydantic Model 类；DB 侧 JSONB，Python 侧 Model 实例。全系统 JSONB 唯一通道（ADR-0009）。
- **Repository[ModelT]** 泛型基类：`get / get_or_none / list / add / delete` 等单聚合原语；子类在各自组件/模块内实现具体查询。返回 ORM Model。
- **AbstractUnitOfWork**：`async with uow: ...`；进入时开 Session，退出未由执行器 commit 自动 rollback。具体 UoW 子类以属性暴露本事务所需 Repository（如 `uow.users: UserRepository`）。
- **UoWExecutor**：kernel/db 持有 UoW 生命周期；`read()` 只读并回滚，`write()` 执行操作后统一 commit。Service 不直接调用 `commit()`。
- **Database**：由 kernel/db 从 Settings 创建 async engine 与 `async_sessionmaker(expire_on_commit=False)`；api/wiring 只消费公开工厂结果。
- **Page\[T\]（Generic 泛型）**：分页封装 `{items: list[T], total: int, page: int, size: int}`。

## 4. 状态机

无。

## 5. 数据库

本组件不建业务表。约定全系统：

- 主键 `uuid`（UUIDv7，Python 生成）；时间 `timestamptz`；枚举存 str；JSON 一律 JSONB（经 JsonBModel）。
- Alembic 异步迁移，`alembic/env.py` 复用本组件 engine 配置；迁移文件是唯一允许裸 SQL 的位置。

## 6. 公开 API

```python
class Base(DeclarativeBase): ...
class TimestampMixin: ...
class JsonBModel(TypeDecorator): ...
class Repository(Generic[ModelT]): ...
class AbstractUnitOfWork: ...
class UoWExecutor: ...
class Database: ...
class Page(BaseModel, Generic[T]): ...
def new_uuid7() -> UUID
```

### HTTP API

无。

## 7. Pipeline

无（本组件被 pipeline 执行器使用）。

## 8. Event

无。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| DB_001 | 500 | 数据库连接失败 | engine 初始化/连接失败 |
| DB_002 | 409 | 事务冲突/唯一约束违例 | IntegrityError 包装 |

## 10. Cron / 任务

无。

## 11. 测试边界

- UoW 未 commit 退出 → 数据回滚（查不到）。
- UoW commit 后 → 数据可见；`updated_at` 自动刷新。
- JsonBModel 往返：Model 实例写入后读出仍是 Model 实例，字段类型正确；非法 payload 写入时报校验错。
- Repository 泛型：`Repository[User]` 返回类型标注为 User（mypy 守护）。
- 唯一约束违例 → DB_002。
- Service 源码中不得出现 `commit()` 或直接访问 `uow.session`。
- UoWExecutor 写操作提交一次，读操作不提交业务写入。
- UUIDv7 生成单调（同毫秒递增可排序）。

## 12. 未决事项

- 只读副本/读写分离：预留 `replica_url` 配置位，本期不实现。
