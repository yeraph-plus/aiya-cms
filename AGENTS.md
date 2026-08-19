# aiya-cms 开发总纲

`context/` 是唯一规格事实来源：后端规格在 `context/spec/`，Astro 用户站规格与设计在 `context/user site spec/`，Vue 管理员端规格在 `context/admin dash spec (SPA)/`。新增或改变行为时，必须按“规格 -> 失败测试 -> 实现 -> 集成验证”推进；三个目录按 owner 分工，不维护 ADR、roadmap、重复合同或第二套长期规格。

## 架构硬约束

- `inc/kernel` 只承载与业务无关的技术运行机制，不得包含用户、角色、OIDC、内容、标签、通知、积分、支付等业务模型或业务流程，也不得导入 `inc/capabilities`、`inc/features` 或 `inc/api`。
- `content`、`access`、`membership` 等 capability 各自拥有自己的业务规则、模型/表和有语义的原子 Command、Query、Activity、事件与迁移；只能导入 kernel 和自身公开/内部代码，不得导入兄弟 capability。跨能力关联使用 opaque ID 和消费方 Port，不建立跨能力 ORM relationship 或数据库外键。
- `inc/features` 是跨能力多步业务流的唯一编排层，例如注册、邮箱验证、密码找回/重置、图床处理和购买流程；只能调用 capability 的公开 Command、Query、Activity、Port 和 DTO，不得访问其 ORM、Repository 或表。
- `inc/api` 是唯一组合根，只做 HTTP DTO/错误适配、认证授权依赖、manifest、Port/provider catalog 注册与解析、router/worker 装配和启动校验；禁止把领域规则、跨表业务或业务流程写进 API，也禁止自动发现、导入即注册和自动路由。
- 当前 `/api/v1/admin/**` 的普通 capability 管理 CRUD 直接调用所属 capability 的公开 Command/Query，不为了形式统一而强行包一层 feature；只有跨 capability、多步骤、可恢复的业务流才进入 `inc/features`。
- `inc/adapters` 的所有允许 provider 必须由组合根在启动构建阶段按稳定 key 全量注册并在 validate/freeze 后固定；运行时只由 settings capability 的 ProviderCatalog/Resolver 选择当前 provider，不按顺序静默尝试或在启动时连接外部服务。
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
- `site`：Astro SSR 用户站，只依赖用户 OpenAPI 与同目录设计合同；规格见 `context/user site spec/`。
- `admin`：Vue 管理员 SPA，只依赖 OpenAPI；规格见 `context/admin dash spec (SPA)/`。
- `alembic`：迁移汇总入口；表与 revision 所有权见 `context/spec/kernel/database.md`。
- `tests`：架构、kernel、capability、feature、API 和端到端测试。

完整阅读顺序和文档状态见 `context/README.md`。修改某项能力时，必须同步该能力规格、迁移、事件/OpenAPI 契约、测试以及受影响的用户站/管理员端消费层。

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
