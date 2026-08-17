# Kernel Database 与迁移规格

## 1. ORM 与表

- 使用 SQLAlchemy 2.x 声明式 `Mapped`/`select()` 风格。
- 禁止业务代码裸 SQL；仅 Alembic 和经规格批准、隔离测试的基础设施优化可使用文本 SQL。
- `Base` 提供统一 metadata，但不因此获得业务表所有权。
- 表名、constraint/index 名全局确定且可由 Alembic 稳定比较。
- 默认主键 UUIDv7；时间列 UTC `timestamptz`。
- JSONB 列必须声明对应 Pydantic 类型和序列化 adapter。

## 2. Repository 与 UoW

- Repository 只封装所属聚合的持久化，不返回 ORM 给 Service/handler。
- 公开读写使用 DTO；ORM 生命周期不得越过 UoW。
- Command handler 接收 UoW factory/Protocol，不接收 Session。
- UoW 显式 commit/rollback；异常默认 rollback。
- 同一 Command 的业务变更和 outbox append 在同一数据库事务中。
- Query 不共享写 UoW，不 flush、不 enqueue event。

kernel 可以提供 Repository、分页和 QuerySpec 原语，但不能提供绕过 capability 规则的通用业务 CRUD Service。

## 3. 并发与锁

- 唯一性和不可超扣等不变量最终由数据库 constraint、条件更新或行锁保证。
- 乐观版本列或悲观锁由 capability 按不变量选择并写入规格。
- 多 worker 领取使用 lease 或 `FOR UPDATE SKIP LOCKED`。
- 禁止依赖进程内锁保证跨进程业务正确性。
- deadlock/serialization failure 必须映射为可分类重试，不无限重试。

## 4. 分页与查询

- page/size 查询返回 `items,total,page,size`，total 使用相同过滤条件。
- 每个查询必须定义稳定排序并以唯一字段收尾。
- 高基数或实时流可定义 cursor contract，但不得在同一 endpoint 混用 page 和 cursor 语义。
- QuerySpec 只能表达已登记字段与操作符，禁止客户端传任意列名或 SQL 片段。

## 5. 表所有权和跨能力引用

- metadata 中每张表登记唯一 owner：`kernel:<component>` 或 `capability:<name>`。
- capability migration 只能修改自身表；修改 kernel 表需 kernel migration owner。
- 跨能力 reference 使用普通标量列，不建立外键或 ORM relationship。
- 跨能力完整性由写入时 Port 校验、业务事件和只读 diagnostics 共同维护。
- 删除 provider 实体前，由 feature/运维流程处理引用；数据库不得跨 capability cascade。

## 6. 迁移布局

- 根 `alembic/env.py` 读取显式 migration manifest，禁止扫描包目录。
- 新 Demo 基线生成根 `alembic/versions/0001_initial.py`，包含全部随发行版交付的 kernel/capability 表。
- `0001_initial` 发布后不可修改；后续 revision 由对应 owner 放入自身 `migrations/`，并登记到根 manifest。
- revision ID 全局唯一，依赖链确定，发布状态只允许一个 deployable head。
- 运行时启用状态不改变 schema 迁移集合，不按 manifest 动态选择 revision。
- migration 必须支持 upgrade/downgrade/upgrade；不可逆数据变更需显式豁免和恢复方案。

## 7. 本次重建

- 删除旧 `0001...0010` 和旧数据库 volume，不提供升级路径。
- 实现期间可使用临时 revision；首个新基线验收前 squash 为一个 `0001_initial`。
- 本轮临时 `0002_comments`、`0003_community` 已在空库发布验收前合并进 `0001_initial`；版本目录只允许保留该一个 deployable revision，comments/community 表、`pg_trgm` 与 trigram/排序索引必须由它一次创建。
- 从新基线发布之时起恢复正常兼容迁移纪律，不再以 Demo 理由改写历史。

## 8. 验收

- 从空 PostgreSQL upgrade 成功，schema 与 metadata diff 为空。
- upgrade/downgrade/upgrade 成功且只有一个 head。
- table owner 检查阻止 capability 修改兄弟表。
- Service/handler Session 泄漏、裸 SQL、无模型 JSONB 被静态测试阻止。
- 并发和事务失败测试证明 outbox 与业务状态不会部分提交。
