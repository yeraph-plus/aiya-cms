# Roadmap

> M 轨为后端，A 轨为管理员 SPA；同号里程碑并行推进并在验收点集成。每个里程碑的完成标准 = 验收项全绿 + 对应质量门全绿 + 文档同步。

| 后端轨 | 管理员轨 | 集成点 |
|---|---|---|
| M0 脚手架 | A0 模板基线（已完成） | 两端均可独立安装、检查与构建 |
| M1 内核 | A1 应用壳（实现完成，真实运行时验收通过，2026-08-05） | auth/me、Capability、统一错误与真实健康检查 |
| M2 内容三件套 | A2 内容管理（操作面板实施中） | 内容、taxonomy、comment 管理闭环 |
| M2.1 声明式内容对象内核重写（计划就绪） | A2 元数据驱动表单/动作 | post/forum/issue 声明注册、迁移与 OpenAPI 收口 |

## M0 脚手架

- venv + pyproject（依赖钉版：fastapi / uvicorn / sqlalchemy[asyncio] / asyncpg / alembic / pydantic / pydantic-settings / apscheduler / redis / aiosmtplib / pyjwt / pwdlib[argon2] / structlog / uuid-utils；dev：pytest / pytest-asyncio / httpx / ruff / mypy）
- `inc/` 包骨架、根 `.gitignore` 与至少一个可执行冒烟测试
- docker-compose.yml（PG16 / Redis7 / mailpit）+ .env.example
- ruff / mypy（kernel strict）/ pytest 配置；`tests/architecture/` 骨架
- Alembic 异步环境（空迁移）
- `codegraph init` 建索引
- 清理仓库根空 txt 文件
- 验收: `docker compose up -d` 后 PG/Redis/mailpit 健康检查通过；`pytest` 至少收集并通过冒烟测试；后端质量门命令全部可执行

## A0 管理员端模板基线（与 M0 并行）

**状态：已完成并封板（2026-08-03）。**

- YummyAdmin 已归入 `admin/` 同仓库维护，MIT License 与来源记录完整，npm 与锁文件成为唯一安装基线。
- 依赖已升级到最新稳定兼容集合；TypeScript 6.0.3 兼容例外已登记。
- `npm ci` 可复现安装；check、typecheck、unit test、build 与 audit 已通过。
- 详细交付证据与封板规则见 [admin/01-a0-a1-plan.md](admin/01-a0-a1-plan.md)。

## A1 管理员端应用壳（与 M1 并行）

**状态：代码与真实运行时验收完成（2026-08-05）；OpenAPI/统一 HTTP、会话与 Capability、显式 mock、健康页及 Chromium 桌面/移动 Playwright 均已通过。**

1. A1.1 产品壳：aiya-cms 品牌、中文默认语言、管理导航与模板业务清理。
2. A1.2 API 契约：OpenAPI 生成客户端、统一 HTTP 层与 `AppError` 映射。
3. A1.3 会话授权：登录/me/刷新/退出、Capability 守卫与 401/403 状态。
4. A1.4 真实联调：显式 mock 模式、真实 M1 链路、健康检查与 Playwright 验收。

详细任务、双轨同步点和完成定义见 [admin/01-a0-a1-plan.md](admin/01-a0-a1-plan.md)；双轨执行顺序见 [m1-a1-plan.md](m1-a1-plan.md)。

## M1 内核

**状态：M1.1–M1.12 已完成（2026-08-04，真实 PG 认证链路与后端质量门通过）；身份事务与凭据失效加固见 ADR-0018，RBAC/Cache 边界见 ADR-0019，Security 原语边界见 ADR-0020，EventBus 生命周期见 ADR-0021，Auth 事务与令牌轮换见 ADR-0022，Pipeline 注册与事务边界见 ADR-0023，Tasks 状态机与唤醒边界见 ADR-0024，Mail/Audit/Settings/API 组合根见 ADR-0025。OpenAPI 冻结方案（ADR-0016）与身份系统设计（ADR-0017）已落库。**

按依赖序实施（每项都遵守 SDD：规格已就位 → pytest 红 → 实现绿）：

1. config / errors / logging
2. db（engine/Base/TimestampMixin/JsonBModel/UUIDv7/UoW/Repository/Page）+ Alembic 首轮迁移
3. cache（Redis/Memory + 单飞 + 内部日志）
4. security（argon2 / JWT / Principal）
5. identity（users/identities/organizations 占位）→ rbac（roles/permissions/别名 seed/Policy）
6. events（EventBus + 失败隔离 + wait_idle）→ auth（注册/登录/双令牌/吊销/限频，发事件故在 events 后）
7. pipeline（Registry/StepContext/Executor + 启动校验 + wiring 完整性测试）
8. tasks（调度器壳/BaseTask/Cron 注册表/LISTEN/NOTIFY 唤醒）
9. mail（outbox + 重投）→ audit（异步落库 + 查询 + 清理 Cron）→ settings（登记制 + 缓存）
10. api 层骨架：app 工厂、全局异常处理、request_id 中间件、deps、wiring.py、健康检查
- 验收: 内核全部测试绿；架构守护测试（依赖红线/Service 无 Session/禁裸 SQL/JSONB 登记）绿；注册→登录→me→refresh→logout 链路在真实 PG 上通过

## M2 内容三件套

1. content（类型注册表 + 泛型 Service + 状态机 + CRUD + 事件 + viewed 计数）
2. taxonomy（term CRUD + assign + 筛选注入 + content.deleted 清理）
3. comment（target 注册 + 树组装 + 防刷 + 状态机 + 注入计数）
4. api 复合响应：ContentDetailResponse（主 DTO + terms 槽 + comment_stats 槽）
- 验收: 三模块文档第 12 节"测试边界"逐条有对应 pytest 且全绿；wiring 完整性测试覆盖全部 key/槽位

**状态：已完成（2026-08-05）**：content / taxonomy / comment 已实现并接入 API、迁移、显式 Pipeline/Event/Cron wiring；OpenAPI 与管理员端类型已重新生成，后端及管理员质量门通过。

### M2.1 声明式内容对象内核重写

**状态：G0/G1/G2/G3/G4/G5/G6/G7/G8 已完成（2026-08-06）。** Content、Taxonomy 与 Comment kernel 的声明层、ORM、DTO、Repository、Service、事件、wiring、`comment_count` 事件维护和 post/forum/issue 显式声明已落地；API 已切换到 kernel Service，旧 content/taxonomy/comment 模块、旧测试和兼容 registry 已删除。ADR-0032 将 content、taxonomy、comment 的通用基实现提升到 kernel，具体 `post`、`forum`、`issue` 由 modules 声明并经 API 显式注册。采用声明键字符串 JSONB、动态状态/转换、`trashed_at + Cron` 和事件维护的 `comment_count`；不提供旧导入路径或旧 DTO 兼容。

执行批次、红测顺序、迁移和质量门见 [0.1.0-declarative-content-kernel-plan.md](0.1.0-declarative-content-kernel-plan.md)，决策全文见 [ADR-0032](adr/0032-declarative-content-object-kernel.md)。

## M3+ 路线（非本期，启动时先写规格文档）

| 序 | 模块 | 关键机制预留 |
|---|---|---|
| 1 | interaction（点赞/收藏/关注/举报） | content.read/comment.read 槽位；target 多态参照 comment |
| 2 | notification / message | mail 组件；事件订阅 |
| 3 | points / 签到 | 事件监听积分流水；Cron 签到结算 |
| 4 | order / payment / refund | **BaseTask + LISTEN/NOTIFY 唤醒**（支付回调）；落表+Cron 补偿 |
| 5 | download 鉴权 | Capability + Policy；短时签名 URL |
| 6 | webhook | mail_outbox 同款"落表+重投"模式 |
| 7 | search（Meilisearch） | ADR-0030 已登记；未来由独立 search 模块配置/调用外部版本化容器，当前不实现 |
