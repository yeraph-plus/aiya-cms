# aiya-cms 重构进度与遗留清单

> 更新于 R4 完成（2026-08）。规格唯一事实源为 `context/spec/`，施工计划为 `context/full-rebuild-plan.md`。
> 本文件只记录**当前未完成**的测试、遗留与后续阶段入口；完成项移出，不留历史。

## 当前状态

- R0（归档）/ R1（规格）/ R2（骨架）/ R3（kernel）/ R4（identity/access/oidc/audit）/ R5（content/taxonomy/settings/assets + post/page 声明）已完成并提交。
- 本地绿态：`pytest` 206 passed、`ruff check/format` 通过、`mypy --strict inc`（137 文件）通过、`alembic upgrade head --sql` 可用（revision 待 R9 squash）。

## 未完成阶段

- [ ] **R6** Notification 与垂直工作流合同样例（待审→通知→异步处理→审核信号→发布）
- [ ] **R7** Points 与 Payments（支付 SDK 厂商选型仍开放）
- [ ] **R8** API 组合根（manifest 装配、Port 绑定、router 挂载、worker 启动）、管理员端重接、生产静态部署
- [ ] **R9** squash 临时迁移为 `0001_initial`、空库升级验收、OpenAPI 快照/TS 类型、Compose 空卷全链路验收

## 待补测试

- [ ] **OpenID conformance**：Basic OP / Config OP / RP-Initiated Logout 目标套件（需真实服务器 + Docker + 外网，本地不可跑）
- [ ] **PostgreSQL 验收**：`FOR UPDATE SKIP LOCKED` 领取分支、outbox/workflow/task 并发、refresh 并发 rotation——当前全部只跑 SQLite
- [ ] **R8 组合根**：空 manifest / 最小 manifest / 完整 manifest 启动差异测试（未启用项无路由/订阅/Cron/worker/连接）
- [ ] **R5+ 能力合同**：content 定时发布重启/并发/取消、置顶分页、taxonomy 孤儿诊断、settings/assets
- [ ] **R7 并发安全**：points 并发不超扣、幂等入账、webhook 重放/乱序/验签
- [ ] **管理员端**：OIDC Code+PKCE 登录、权限可见性、真实 API E2E、生产 build（禁 Vite dev/preview 承载）
- [ ] **PostgreSQL 迁移验收**：`alembic/versions/` 目前无 revision（R9 统一 squash 为 `0001_initial`）；空库 upgrade 会按 manifest 全量建表并校验 schema/metadata 一致

## 遗留事项

- [ ] **R5 已覆盖**：content 定时发布（重启重扫/重复扫描/取消/重排失效）、置顶分页、taxonomy 规则与孤儿诊断、settings seo 组、assets 工作流幂等均已实现并有测试；**R5 待 Docker 环境补 PostgreSQL 专项**（SKIP LOCKED 分支、并发 worker 扫描）
- [ ] 旧 PostgreSQL volume（compose project `aiya-cms`）删除——Docker daemon 当前未运行，R9 空库验收前必须做
- [ ] Compose / Dockerfile 审计改写（plan §12）：`uvicorn inc.main:app`、`python -m inc.cli`、`openapi-check` 等入口在 R8 前不可用；Dockerfile 已移除旧 openapi COPY
- [ ] `inc/main.py` 为占位模块，`create_app` 属 R8
- [ ] `openapi.json` / `openapi.sha256` 待 R9 重新生成；admin 生成的 TS 类型待重接
- [ ] kernel `cache` Port 未建（无真实消费者；出现第二个用例再抽象）
- [ ] OIDC Port 绑定（identity/access → oidc）与生产签名密钥加载器（env/file/KMS）属 R8 组合根
- [ ] 管理员 SPA 作为 first-party public client 接入（R8）；长期会话需 BFF/httpOnly adapter 决策
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
