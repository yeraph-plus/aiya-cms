# 依赖规则（01-dependency-rules）

## 1. 依赖矩阵

| 导入方 ↓ 被导入方 → | kernel | modules.a | modules.b | api |
|---|---|---|---|---|
| **kernel** | ✅ 内部组件间 | ❌ 绝对禁止 | ❌ 绝对禁止 | ❌ |
| **modules.a** | ✅ 仅限公开 API | ✅ 包内部 | ❌ 绝对禁止 | ❌ |
| **modules.b** | ✅ 仅限公开 API | ❌ 绝对禁止 | ✅ 包内部 | ❌ |
| **api** | ✅ | ✅ | ✅ | ✅ |
| **tests** | ✅ | ✅ | ✅ | ✅ |

补充细则：

1. **kernel 绝对禁止导入 modules**。内核不知道任何业务模块的存在，包括模块定义的常量、类型、事件名。反向协作全部通过内核抽象（PipelineRegistry / EventBus / Capability 注册表）完成。
2. **modules.a 绝对禁止导入 modules.b**。包括"只 import 一个类型"也不行——类型层面的共享需求上移到 kernel（极少，需 ADR）或在 api 层组合。
3. **api 层可自由导入**。api 是组合根（Composition Root）：装配 wiring、定义复合响应 DTO、做读聚合。
4. kernel 内部组件也遵守单向依赖（见第 4 节）。
5. 第三方库（fastapi、sqlalchemy 等）任何层可用，但 **Session 只能出现在 kernel/db 与 Pipeline 执行器内**（见第 3 节）。

## 2. 守护方式

依赖规则不靠自觉，靠**架构守护测试**（`tests/architecture/`）：

- `test_kernel_does_not_import_modules.py`：扫描 `inc/kernel/**/*.py` 的 import 语句，出现 `inc.modules` 即失败。
- `test_modules_do_not_cross_import.py`：扫描 `inc/modules/<name>/` 的 import，出现 `inc.modules.<other>` 即失败。
- `test_service_has_no_session.py`：扫描所有 `services.py`（kernel + modules），出现 `AsyncSession`、`inc.kernel.db.session` 相关 import 即失败。
- `test_no_raw_sql.py`：扫描 `inc/**`（alembic 除外），出现 `sqlalchemy.text(` 或 `from sqlalchemy import text` 即失败。
- `test_jsonb_has_pydantic_model.py`：ORM 模型中所有 JSONB 列必须在同模块 `schemas.py` 存在对应 Model 登记（登记方式见 [02-data-boundaries.md](02-data-boundaries.md)）。

工具选型：首选用 Python AST 解析的自写 pytest（零额外依赖、规则可定制）；不引入 import-linter 等外部工具（保持工具链最小）。

## 3. 分层内部规则

### 3.1 四层调用约定

| 层 | 职责 | 禁止 |
|---|---|---|
| api | HTTP 适配、参数解析、依赖注入、wiring、复合 DTO、读聚合 | 业务逻辑、直接访问 Repository |
| Service | 业务逻辑、事务编排（经 Pipeline/UoW）、DTO↔ORM 转换 | import/接收 Session、手写 dict 操作 JSONB、跨模块 import |
| Repository | 单聚合的持久化查询，返回 ORM Model | 返回 DTO、跨聚合查询（跨聚合在 Service 组合） |
| ORM Model | 表映射 | 业务逻辑 |

### 3.2 kernel 内部依赖顺序

```
config → errors → logging → db → cache
  → security → identity → rbac → events → auth
  → pipeline → tasks → mail
  → audit / settings（依赖 db + events + tasks）
  → content（依赖 db + security + rbac + events + pipeline + tasks）
  → taxonomy（依赖 content 的只读类型目录）
  → comment（依赖通用 TargetExists 协议，不导入具体内容类型）
```

上层可依赖下层，禁止反向。`events` 位置刻意靠前（仅依赖 errors+logging）：包括 auth 和 CMS 对象组件在内的后续组件都可发事件；EventBus 本身不依赖任何业务组件。Content/Taxonomy/Comment 的归属与声明边界见 ADR-0032。

## 4. 跨模块协作的两种合法通道

1. **读取聚合（注入点）**：模块 B 定义 step 函数与槽位 DTO；api 层 wiring 把 step 挂到模块 A 的读 Pipeline 的 `after` 列表；运行时 step 从 `StepContext.principal` + `payload` 取要素，写入 `extensions[slot_key]`。详见 [../kernel/pipeline.md](../kernel/pipeline.md)。
2. **写入解耦（EventBus）**：模块 A 发事件，模块 B 的监听器（经 wiring 装配）异步消费并在自己的表里完成写入。详见 [../kernel/events.md](../kernel/events.md)。

除这两条通道外不存在第三种跨模块数据流动方式。共享数据库不等于共享代码：模块 B 可以查询模块 A 的表吗？——**不允许直接查**。模块 B 需要模块 A 的数据时：读取走 api 聚合或订阅事件落本地冗余；确需直接读表的极端情况必须提 ADR 并在双方文档中登记。
