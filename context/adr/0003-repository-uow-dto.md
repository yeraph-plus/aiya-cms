# ADR-0003: UoW + Repository 端口与 DTO 边界（Service 禁 Session）

- 状态: accepted
- 日期: 2026-08-02
- 决策者: 项目所有者 + AI 协作
- 关联: [architecture/02-data-boundaries.md](../architecture/02-data-boundaries.md)、[kernel/db-uow-repository.md](../kernel/db-uow-repository.md)

## 背景

所有者提出两条硬要求：① "Service 不能访问 Session"；② 读写事务要有"显式 Pipeline 通用标准的事务函数约定"。需要一种机制让 Service 做业务编排的同时完全不接触 SQLAlchemy Session，且多步写操作共享一个事务边界。

## 决策

1. **Repository 端口**：每个聚合一个 Repository 类，封装该聚合的全部持久化查询，**返回 ORM Model**。Session 只存在于 Repository 实现与 UoW 内部。
2. **Unit of Work**：`AbstractUnitOfWork`（异步上下文管理器）持有 Session，聚合本事务用到的 Repository 实例；`commit()`/`rollback()` 只在此处出现。
3. **Service**：只依赖 Repository（经 UoW 获取），入参出参一律 **Pydantic DTO**；DTO↔ORM 转换只发生在 Service 边界。
4. **Pipeline 执行器**（kernel）统一持有 UoW 生命周期：before steps → core → commit → after steps，一个 Pipeline 运行 = 一个事务（ADR-0006）。
5. 守护：`tests/architecture/test_service_has_no_session.py` 扫描所有 services.py 禁止出现 Session 相关 import。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| Service 接收 UoW 门面自行 commit | 少一层执行器 | 事务边界分散在各 Service，before/after 注入点无处安放 | 与 Pipeline 事务约定冲突 |
| Service 直接用 Session（FastAPI 常见风格） | 直接、样板少 | 违反所有者硬要求；业务与持久化耦合 | 明确被否 |
| 仓储返回 DTO | Service 更薄 | 转换逻辑下沉导致 ORM 泄露/重复转换；写路径无法表达 | 转换集中在 Service 边界更清晰 |

## 后果

### 正面
- Service 可纯内存单测（fake Repository），不需要数据库。
- 事务边界全局唯一形态，审计、事件、缓存失效都有统一挂点。

### 负面 / 代价
- 样板代码增多（每个聚合一套 Repository + DTO）。
- 复杂查询（跨聚合联表）需要在 Service 组合多个 Repository，或提 ADR 开受控例外。

### 逃生门
- 个别重查询场景允许在 api 层经 kernel 的只读查询通道直出（只读，不进 Service 写路径），需 ADR 登记。
