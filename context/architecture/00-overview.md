# 架构总览（00-overview）

## 1. 项目目标

aiya-cms 是一个基于 **FastAPI + SQLAlchemy 2.0 + PostgreSQL** 的无头 CMS 通用应用底座，并在同一仓库内维护 Vue 3 管理员 SPA。目标是以一套底层支撑多种内容站点形态：下载站、图库站、博客、轻社区。这些站点的底层能力（用户、认证、权限、内容、分类、评论、审计、任务、缓存、邮件）几乎一致，因此沉淀为**内核层 + 模块层**的可复用底座，长期迭代。

设计参照 WordPress 的对象抽象（Post / Taxonomy / Metadata / User / Capability / Event Bus / Task / Cache），**只借鉴抽象，不复刻表结构**；用 PostgreSQL JSONB + Pydantic 强类型取代 wp_postmeta 的 EAV 反模式。

## 2. 分层结构

```
┌─────────────────────────────────────────────────────┐
│ admin/ 管理员 SPA（Vue 3 / TypeScript / Vite）       │
│        仅经 HTTP/OpenAPI 契约访问 api                 │
└───────────────────────┬─────────────────────────────┘
                        │ HTTPS / JSON
┌─────────────────────────────────────────────────────┐
│ api 层（HTTP 适配、依赖注入、组合装配 wiring、        │
│         复合响应 DTO、读聚合）—— 可自由导入所有层      │
├─────────────────────────────────────────────────────┤
│ modules/  业务类型（post / forum / issue）及扩展模块   │
│           interaction, notification, points,         │
│           order, download, webhook, search …         │
│           模块之间禁止互相 import                     │
├─────────────────────────────────────────────────────┤
│ kernel/   内核（config, errors, logging, db/uow,     │
│           security, identity, auth, rbac, audit,     │
│           settings, events, pipeline, cache, tasks,  │
│           mail, content, taxonomy, comment）          │
│           —— 绝对禁止导入 modules                     │
├─────────────────────────────────────────────────────┤
│ 基础设施  PostgreSQL 16 / Redis 7 / SMTP(mailpit) /   │
│           APScheduler（被 kernel 壳封装）             │
└─────────────────────────────────────────────────────┘
```

依赖方向只允许自上而下。完整依赖矩阵见 [01-dependency-rules.md](01-dependency-rules.md)。

管理员 SPA 是本仓库的一等交付物，但不属于后端 Python 分层。它禁止导入后端源码或复制 Pydantic DTO；A1 起由 FastAPI OpenAPI 生成 TypeScript API 类型与客户端。前后端通过版本化 `/api/v1` 契约协作，后端 Capability 是授权权威，前端权限守卫只负责交互可见性。

## 3. 内核层（稳定承诺）

> ADR-0032 已冻结 M2.1 归属调整：Content、Taxonomy、Comment 的通用对象模型和基实现属于 kernel；kernel 不提供具体内容类型。`post`、`forum`、`issue` 仍由 modules 声明，并由 api 组合根显式登记。迁移计划见 `context/0.1.0-declarative-content-kernel-plan.md`。

内核层在初版完成通用设计后**封装暴露、轻易不变动**。内核包含两类东西：

1. **基础设施引入或封装**：PG（engine/session/UoW）、APScheduler（调度器壳）、SMTP、Redis（Cache 抽象）、结构化日志。
2. **核心逻辑**：Identity/User/Organization（占位）/Role/Permission（RBAC）、Audit、Setting、EventBus、Pipeline 注册表、BaseTask 状态机、Content/Taxonomy/Comment 通用对象、错误码体系。

内核在正式契约冻结后的稳定承诺是公开 API 签名向后兼容、基础表结构（identities / users / organizations / roles / permissions / audit_logs / settings / task_instances / mail_outbox / contents / terms / term_relationships / comments）只增不毁；当前 0.1.0 初步设计阶段允许通过 ADR 直接替换未冻结的字段和方法。

## 4. 模块层

> ADR-0032 实施后，模块层承载具体内容类型和扩展业务，不再拥有 content/taxonomy/comment 通用表与基 Service。现有三模块目录仅作为 M2.1 迁移输入，不再扩展。

模块层承载具体内容类型（post/forum/issue）和可替换业务扩展（interaction、积分、通知、支付、搜索等）。模块特征：

- **按需拥有表结构**：声明型内容模块可以只提供 ContentType；拥有独立聚合的扩展模块自己维护表与业务数据。模块不得复制内核对象表，也不得把所有业务塞进 JSONB 万能字段。
- **吸取微服务优点但不独立部署**：共享数据库、功能内聚、经 Service 层与 EventBus 协作；模块只从内核获取用户要素（Principal）。
- **模块之间零 import**：读取协作由 api 层聚合（注入点），写入协作仅经 EventBus 异步解耦。

## 5. 读 / 写路径（同步只读规则）

### 5.1 规则原文

> 同步函数只读表，异步函数不限制。读取路径（GET 接口、页面数据组装、QueryService）严禁任何写操作与事件副作用；全部写操作走异步 Command/Action API，写后事件由 EventBus 异步派发。

典型场景（内容购买）：同步 GET 直查购买状态 → 浏览器异步 POST 到 commerce 模块完成购买 → 下次 GET 同步直读到"已购买"状态继续渲染。读路径永远不夹杂写。

### 5.2 读路径

```
HTTP GET → api handler
  → 主模块 QueryService（只读，返回 DTO）
  → 读 Pipeline 的 after 注入点：各模块 step 填充扩展槽
      （StepContext.extensions[slot_key] = XxxDTO）
  → api 层组装复合响应 DTO（强类型，直接 import 各模块 DTO）
  → HTTP 响应
```

约束：QueryService 不开写事务、不发事件、不写缓存之外的任何存储；缓存读/写（get_or_set）视为读路径的合法组成部分（缓存写不产生业务副作用）。

### 5.3 写路径

```
HTTP POST/PATCH/DELETE → api handler
  → CommandService 的方法（仅一个模块内）
  → Pipeline 执行器：before steps → core（业务）→ UoW.commit
  → commit 成功后：after steps 运行，发布领域事件
  → EventBus 异步派发给监听器（其他模块的写入在监听器中完成）
```

**跨模块写入只经 EventBus**。禁止模块 A 的 Service 同步调用模块 B 的写接口（事实上也不可能——模块间禁止 import）。

## 6. 关键机制速览

| 机制 | 一句话 | 规格文档 |
|---|---|---|
| UoW / Repository | Service 不见 Session；Repo 返回 ORM，Service 进出 DTO | [../kernel/db-uow-repository.md](../kernel/db-uow-repository.md) |
| Pipeline 注册表 | `PipelineKey` + 显式装配 + 启动 fail-fast 校验，无自动发现 | [../kernel/pipeline.md](../kernel/pipeline.md) |
| EventBus | 进程内 asyncio 派发，失败隔离，Cron 补偿兜底 | [../kernel/events.md](../kernel/events.md) |
| BaseTask | 抽象基类模板方法：run/on_success/on_failure/rollback + 状态机 | [../kernel/tasks.md](../kernel/tasks.md) |
| LISTEN/NOTIFY | 仅用于任务即时唤醒（如支付回调），非通用总线 | [../kernel/tasks.md](../kernel/tasks.md) |
| RBAC | 操作别名 = Permission + Policy 纯函数，最小模型 | [../kernel/rbac.md](../kernel/rbac.md) |
| Cache | Protocol + Redis/Memory 双实现，封装内集成日志 | [../kernel/cache.md](../kernel/cache.md) |

## 7. 技术基线

| 项 | 决策 |
|---|---|
| 语言 | Python 3.14 |
| 依赖管理 | pip + venv + `pyproject.toml`（PEP 621，版本精确钉死） |
| Web | FastAPI + Pydantic v2 |
| ORM | SQLAlchemy 2.0 async（asyncpg）+ Alembic 异步迁移 |
| 调度 | APScheduler 3.x（AsyncIOScheduler，内核壳封装） |
| 缓存 | Redis 7（redis-py async），内存降级实现 |
| 邮件 | aiosmtplib（dev 用 mailpit） |
| 认证 | PyJWT 双令牌 + pwdlib[argon2] |
| 基础设施 | docker-compose：PostgreSQL 16 / Redis 7 / mailpit |
| 质量门 | ruff + mypy（kernel strict）+ pytest（pytest-asyncio + httpx） |
| 代码查询 | codegraph（优先于 grep） |
| 管理员端 | Node.js 24 + npm + Vue 3 + TypeScript + Vite + Naive UI + Pinia |
| 管理员端测试 | Biome + vue-tsc + Vitest；关键链路后续增加 Playwright |

## 8. 长期演进方向（非本期）

interaction（点赞/收藏/关注/举报）、notification、message、points/签到、order/payment/refund、下载鉴权、webhook、Meilisearch 搜索适配。内核已为之预留：EventBus、Pipeline 注入点、Capability 登记、BaseTask、JSONB+泛型内容类型。详见 [../roadmap.md](../roadmap.md)。
