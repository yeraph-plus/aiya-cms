# aiya-cms 重构进度与遗留清单

> 更新于 R4 完成（2026-08）。规格唯一事实源为 `context/spec/`，施工计划为 `context/full-rebuild-plan.md`。
> 本文件只记录**当前未完成**的测试、遗留与后续阶段入口；完成项移出，不留历史。

## 当前状态

- R0（归档）/ R1（规格）/ R2（骨架）/ R3（kernel）/ R4（identity/access/oidc/audit）/ R5（content/taxonomy/settings/assets + post/page 声明）已完成并提交。
- R8 后端组合根已完成（manifest 装配/Port 绑定/容器 freeze/worker 生命周期、OIDC bearer 校验、admin routers、错误 DTO、OpenAPI 快照 + CLI）。R6/R7 已按指示跳过。
- **R9 已完成并验收**：`alembic/versions/0001_initial`（31 表，空 PostgreSQL upgrade/downgrade 往返 + `alembic check` 无漂移）、`inc/cli.py create-admin`（幂等 + 一次性密码）、compose/Dockerfile 生产就绪（`inc.main:get_app --factory`、PYTHONPATH、openapi.json COPY、python-multipart 依赖、移除 admin 服务待前端独立计划）、容器全链路验收通过（migrate→api healthy→create-admin→auth/me+内容+审计+settings 冒烟→openapi-check→backend-quality→backend-test 270 passed）。
- 本地绿态：`pytest` 270 passed、`ruff check/format` 通过、`mypy --strict inc`（152 文件）通过、`alembic check` 无漂移、`inc.main openapi-check` 通过。

## 未完成阶段

- [ ] **R9 余项**：OpenID conformance 目标套件（需外网 + 真实服务器）；管理员 SPA（用户独立计划，compose 已移除 admin 服务）；OIDC client 静态注册入口；生产签名密钥加载器（env/file/KMS，现用 InMemorySigningKeyStore）；Redis 接入（cache Port 无消费者，未启用）
- [ ] **R6** Notification 与垂直工作流合同样例（待审→通知→异步处理→审核信号→发布）
- [ ] **R7** Points 与 Payments（支付 SDK 厂商选型仍开放）

## 待补测试

- [ ] **OpenID conformance**：Basic OP / Config OP / RP-Initiated Logout 目标套件（需真实服务器 + Docker + 外网，本地不可跑；前置：OIDC client 静态注册入口）
- [ ] **PostgreSQL 专项（已部分完成）**：SKIP LOCKED 领取分支与 refresh 并发 rotation 的专项并发测试待补（容器验收已覆盖迁移/冒烟/往返，未覆盖并发注入）
- [ ] **CORS/生产配置**：cors_origins 精确 allowlist、allow_credentials=False、token 响应 cache 头（http-openapi §12，当前无测试）
- [ ] **管理员端**：OIDC Code+PKCE 登录、权限可见性、真实 API E2E、生产 build（禁 Vite dev/preview 承载）——前端独立计划
- [ ] **PostgreSQL 迁移验收**：`0001_initial` 已生成并完成空库 upgrade/downgrade 往返 + `alembic check` 无漂移；后续 revision 按 owner 向前迁移

## 遗留事项

- [ ] 旧 PostgreSQL volume 数据已清空重建（R9 空库验收）；compose project `aiya-cms` 的 volume 保留复用
- [ ] 容器 stop 无 drain 宽限期（composition.md §6）：直接 cancel 依赖 lease 过期恢复，grace period 待补
- [ ] admin readmodel providers 未实现（`admin_summary_registry` 为空注册）；R8/R9 余项
- [ ] FeatureSpec 与 composition.md §2.2 对齐（workflows/events/Cron/routers/ports 字段）待扩展
- [ ] 生产签名密钥加载器（env/file/KMS）未实现，现用 InMemorySigningKeyStore（container 与 CLI 均如此）
- [ ] kernel `cache` Port 未建（无真实消费者；出现第二个用例再抽象）——compose 已起 Redis 但后端未接入
- [ ] 宿主环境说明：本地跑 kernel/capability 测试需 `pip install` dev 依赖（aiosqlite/httpx/anyio≥4.9/asyncpg/python-multipart 等），完整门禁以 compose 为准

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
