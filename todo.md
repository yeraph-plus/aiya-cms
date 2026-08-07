# aiya-cms 重构进度与遗留清单

> 更新于 R4 完成（2026-08）。规格唯一事实源为 `context/spec/`，施工计划为 `context/full-rebuild-plan.md`。
> 本文件只记录**当前未完成**的测试、遗留与后续阶段入口；完成项移出，不留历史。

## 当前状态

- R0（归档）/ R1（规格）/ R2（骨架）/ R3（kernel）/ R4（identity/access/oidc/audit）/ R5（content/taxonomy/settings/assets + post/page 声明）已完成并提交。
- R8 后端组合根已完成：manifest 装配/Port 绑定/容器 freeze/worker 生命周期、OIDC bearer 校验 + AppContext、admin routers（identity/access/content/taxonomy/settings/assets/audit/health/auth）、错误 DTO 归一化、`openapi.json`+`openapi.sha256` 快照与 `inc.main openapi-dump/check` CLI。R6/R7 已按指示跳过（notification/points/payments 不在首轮闭环）。
- 已做一轮静态代码审查并修复（条件更新防并发丢失更新、事件/审计携带真实 id、kernel JsonBModel 去嵌套、publish 竞态条件更新、storage error 透传、finalize/delete 审计、DeleteReconciler 等）。
- 本地绿态：`pytest` 270 passed、`ruff check/format` 通过、`mypy --strict inc`（151 文件）通过、`alembic upgrade head --sql` 可用、`inc.main openapi-check` 通过。
- API 层已做一轮代码审查并修复：容器 stop/start 幂等、manifest routers/workers/重复项 fail-fast、handler-schema 交叉校验、生产拒绝 dev_memory、OIDC 挂载按 manifest 门控、router 权限 key 启动校验、X-Request-ID 字符集白名单、/auth/me 仅认证、kid 精确校验 + leeway + openid scope + WWW-Authenticate、settings 组级权限、bootstrap-admin 端点移除、purge DTO、assets 只读端点权限修复、access 事件 schema 补注册。

## 未完成阶段

- [ ] **R8 余项**：管理员 SPA 按新 OpenAPI 重接（OIDC Code+PKCE 登录、users/roles/content/taxonomy/settings/assets 页面、diagnostics 概览、生产 build 与静态部署容器）；OIDC client 静态注册入口（当前为 SQL/迁移直插）；生产签名密钥加载器（env/file/KMS，现用 InMemorySigningKeyStore）
- [ ] **R6** Notification 与垂直工作流合同样例（待审→通知→异步处理→审核信号→发布）
- [ ] **R7** Points 与 Payments（支付 SDK 厂商选型仍开放）
- [ ] **R9** squash 临时迁移为 `0001_initial`、空库升级验收、OpenAPI 快照/TS 类型、Compose 空卷全链路验收

## 待补测试

- [ ] **OpenID conformance**：Basic OP / Config OP / RP-Initiated Logout 目标套件（需真实服务器 + Docker + 外网，本地不可跑）
- [ ] **PostgreSQL 验收**：`FOR UPDATE SKIP LOCKED` 领取分支、outbox/workflow/task 并发、refresh 并发 rotation——当前全部只跑 SQLite
- [ ] **CORS/生产配置**：cors_origins 精确 allowlist、allow_credentials=False、token 响应 cache 头（http-openapi §12，当前无测试）
- [ ] **管理员端**：OIDC Code+PKCE 登录、权限可见性、真实 API E2E、生产 build（禁 Vite dev/preview 承载）
- [ ] **PostgreSQL 迁移验收**：`alembic/versions/` 目前无 revision（R9 统一 squash 为 `0001_initial`）；空库 upgrade 会按 manifest 全量建表并校验 schema/metadata 一致

## 遗留事项

- [ ] 旧 PostgreSQL volume（compose project `aiya-cms`）删除——Docker daemon 当前未运行，R9 空库验收前必须做
- [ ] 容器 stop 无 drain 宽限期（composition.md §6）：直接 cancel 依赖 lease 过期恢复，grace period 待 R9 前补
- [ ] admin readmodel providers 未实现（`admin_summary_registry` 为空注册）；R8 余项
- [ ] FeatureSpec 与 composition.md §2.2 对齐（workflows/events/Cron/routers/ports 字段）待扩展
- [ ] Compose / Dockerfile 审计改写（plan §12）：入口改为 `uvicorn inc.main:get_app` / `python -m inc.main`，openapi-check 挂进 backend-quality 门禁
- [ ] OIDC Port 绑定（identity/access → oidc）已在组合根完成；生产签名密钥加载器（env/file/KMS）未实现，现用 InMemorySigningKeyStore
- [ ] `openapi.json` / `openapi.sha256` 已在 R8 生成并纳入版本库；admin 生成的 TS 类型待重接
- [ ] 管理员 SPA 作为 first-party public client 接入（R8 余项）；长期会话需 BFF/httpOnly adapter 决策
- [ ] kernel `cache` Port 未建（无真实消费者；出现第二个用例再抽象）
- [ ] 宿主环境说明：本地跑 kernel/capability 测试需 `pip install` dev 依赖（aiosqlite/httpx/anyio≥4.9 等），完整门禁以 compose 为准

## 验证命令

```powershell
python -m pytest tests
python -m ruff check .
python -m ruff format --check .
python -m mypy inc
python -m alembic upgrade head --sql
# Docker 启动后：
docker compose --profile test run --rm backend-quality
docker compose --profile test run --rm backend-test
```
