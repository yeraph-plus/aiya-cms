# aiya-cms 开发总纲

`context/spec/` 是唯一规格事实来源。新增或改变行为时，必须按“规格 -> 失败测试 -> 实现 -> 集成验证”推进；不维护 ADR、roadmap 或第二套长期规格。

## 架构硬约束

- `inc/kernel` 只承载技术运行机制，不得包含用户、角色、OIDC、内容、标签、通知、积分、支付等业务模型，也不得导入 `inc/capabilities`、`inc/features` 或 `inc/api`。
- capability 只能导入 kernel 和自身公开/内部代码，不得导入兄弟 capability；跨能力关联使用 opaque ID 和消费方 Port，不建立跨能力 ORM relationship 或数据库外键。
- `inc/features` 是跨能力业务编排层，只能调用 capability 的公开 Command、Query、Activity、Port 和 DTO，不得访问其 ORM、Repository 或表。
- `inc/api` 是唯一组合根，负责显式选择 manifest、实现 Port、挂载 router、注册 worker，并在启动时 validate、freeze；禁止自动发现、导入即注册和自动路由。
- 未装配的 capability/feature 不得产生路由、订阅、Cron、worker、外部连接、线程或后台协程。随发行版交付的表统一迁移，迁移存在不代表运行时启用。
- Service/Command handler 不接收 Session，只经 Repository/UoW；边界使用 Pydantic DTO；禁止裸 SQL。JSONB 字段必须绑定 Pydantic 模型。
- 读路径不得写库、发事件或隐式计数。跨能力写入只经公开 Command/Activity；异步副作用必须由同事务 outbox 和幂等 inbox/handler 承担。
- kernel 只提供 Repository/UoW、分页和查询规格等 IO 原语；业务写入必须使用有语义的 Command，禁止万能业务 CRUD 绕过权限、审计、幂等或状态机。
- workflow、activity、事件、Cron、内容类型、积分行为、Capability、Feature 和 Router 必须使用稳定 key 显式注册，并在启动时 fail-fast。
- 管理员端只消费 FastAPI OpenAPI 生成类型；后端是最终授权边界。生产管理员站点必须使用正式静态文件服务，不得运行 Vite dev server 或 `vite preview`。

## 目录与规格

- `inc/kernel`：技术内核；规格见 `context/spec/kernel/`。
- `inc/capabilities`：可独立装配的业务能力；规格见 `context/spec/capabilities/`。
- `inc/features`：垂直业务声明与持久化工作流；规格见 `context/spec/features.md`。
- `inc/adapters`：外部 Port 实现库，按 capability 分目录，可被 api 与 feature 使用；规格见 `context/spec/adapters.md`。
- `inc/api`：应用组合根与 HTTP 适配层；规格见 `context/spec/composition.md` 和 `context/spec/http-openapi.md`。
- `admin`：Vue 管理员 SPA，只依赖 OpenAPI；规格见 `context/spec/admin.md`。
- `alembic`：迁移汇总入口；表与 revision 所有权见 `context/spec/kernel/database.md`。
- `tests`：架构、kernel、capability、feature、API 和端到端测试。

完整阅读顺序和文档状态见 `context/README.md`。修改某项能力时，必须同步该能力规格、迁移、事件/OpenAPI 契约、测试以及管理员消费层。

## 运行与验证

宿主机使用 Docker Compose（infra 单独管理 PostgreSQL/Redis，backend 镜像内建全部一次性命令）：

```powershell
docker compose -f compose.infra.yaml up -d
docker compose up -d --build
docker compose run --rm backend python -m inc.cli migrate
docker compose run --rm backend python -m inc.cli install
docker compose run --rm backend python -m inc.cli quality
docker compose run --rm backend python -m inc.cli test
docker compose run --rm backend python -m inc.cli openapi-check
docker compose run --rm backend python -m inc.cli migration-check
```

规格重构期间，旧实现与新版规格暂时不一致必须由失败测试或明确的重构阶段记录体现；不得用兼容层把旧架构重新引入。完整发布门见 `context/spec/quality-release.md`。
