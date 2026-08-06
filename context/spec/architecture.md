# aiya-cms 架构规格

## 1. 分层

- `inc/kernel` 是稳定内核，只提供基础设施、通用对象与公开 DTO/Protocol。
- `inc/modules` 承载具体业务类型和可替换业务；模块不得互相 import，kernel 不得 import modules。
- `inc/api` 是唯一组合根，负责显式装配 services、registries、routers、pipelines、events、cron 与复合 DTO。
- `admin/` 是 HTTP/OpenAPI 客户端，不读取 Python 源码，不复制后端 DTO。

## 2. 数据与事务边界

- 主键使用 UUIDv7；时间使用 UTC、tz-aware timestamptz；枚举持久化为字符串。
- Service 只接收/返回 Pydantic DTO，不接收 Session；Repository/UoW 负责 ORM 与事务。
- 禁止裸 SQL；仅 SQLAlchemy 2.0 `select()`/`Mapped` 风格，Alembic 是唯一迁移例外。
- JSON 列统一 JSONB，并绑定对应 Pydantic Model；Service 不手写 JSONB dict 变更。
- 读路径禁止业务写入和事件副作用；写路径为 Command → Pipeline/UoW → commit → after/EventBus。

## 3. 注册与装配

- Capability、事件、Pipeline key、扩展槽、错误码、Cron 名必须先登记后使用。
- 禁止自动发现；模块由 API 组合根按固定顺序显式注册并在启动时 fail-fast 校验、冻结。
- 跨模块读取由 api 聚合或 Pipeline 槽位完成；跨模块写入只通过 EventBus。

## 4. 冻结策略

- `inc/kernel` 当前公开导入、DTO、事件、错误码、Capability、Pipeline key 与基础表结构组成 `kernel-v0.1.0` 稳定面。
- kernel 只接受兼容修复；破坏性改变必须先更新本规格并提高内核版本。
- API 组合根、Alembic、OpenAPI 和管理员端可随仓内模块演进；新增模块后重建镜像。
- Compose 运行单个 API 实例，因此 APScheduler 只启动一个调度器实例。
