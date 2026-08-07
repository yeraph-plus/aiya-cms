# aiya-cms 重构进度与遗留清单

> 更新于 R4 完成（2026-08）。规格唯一事实源为 `context/spec/`，施工计划为 `context/full-rebuild-plan.md`。
> 本文件只记录**当前未完成**的测试、遗留与后续阶段入口；完成项移出，不留历史。

## 当前状态

- R0（归档）/ R1（规格）/ R2（骨架）/ R3（kernel）/ R4（identity/access/oidc/audit）/ R5（content/taxonomy/settings/assets + post/page 声明）已完成并提交。
- R8 后端组合根已完成。R9 已完成并验收（`0001_initial` + 空库往返 + compose 全链路 + 容器门禁）。
- **R6 已完成**（b9bdb3b）：notification capability（spec/模板/三表/intent+delivery/Port/commands/`notification.deliver.v1` workflow/事件/诊断）+ SMTP adapter 封装（aiosmtplib，错误分类/idempotency key/超时 unknown）+ 垂直工作流合同 fixture（待审→通知→审核信号→发布，崩溃恢复 + 副作用不重复 + 未声明信号拒绝）。**mailpit 仅临时用于 adapter 集成验证（收件确认后已删除），compose 不集成**。
- 本地绿态：`pytest` 285 passed + 3 skipped（mailpit 缺失时 adapter 集成自动跳过）、`ruff check/format` 通过、`mypy --strict inc`（161 文件）通过、`alembic check` 无漂移、容器 backend-test/backend-quality/migration-check/openapi-check 全绿。

## 未完成阶段

- [ ] **R7** Points 与 Payments（支付 SDK 厂商选型仍开放）
- [ ] **R9 余项**：OpenID conformance 目标套件（需外网 + 真实服务器）；管理员 SPA（用户独立计划）；OIDC client 静态注册入口；生产签名密钥加载器（现用 InMemorySigningKeyStore）；Redis 接入（cache Port 无消费者，未启用）

## 待补测试

- [ ] **OpenID conformance**：Basic OP / Config OP / RP-Initiated Logout 目标套件（需真实服务器 + Docker + 外网，本地不可跑；前置：OIDC client 静态注册入口）
- [ ] **PostgreSQL 专项**：SKIP LOCKED 领取分支与 refresh 并发 rotation 的专项并发测试待补（R9 已覆盖迁移/冒烟/往返）
- [ ] **CORS/生产配置**：cors_origins 精确 allowlist、allow_credentials=False、token 响应 cache 头（http-openapi §12，当前无测试）
- [ ] **管理员端**：OIDC Code+PKCE 登录、权限可见性、真实 API E2E、生产 build（禁 Vite dev/preview 承载）——前端独立计划
- [ ] **notification 收尾**：SMS adapter 合同测试（规格 §8 "Email 与 SMS fake adapters 通过相同合同测试"——SMTP 已验证，SMS 待 R7 或补充）；`notification` 装配进测试 manifest 的集成测试待补（当前仅 capability 级）

## 遗留事项

- [ ] 旧 PostgreSQL volume 数据已清空重建（R9 空库验收）；compose project `aiya-cms` 的 volume 保留复用
- [ ] 容器 stop 无 drain 宽限期（composition.md §6）：直接 cancel 依赖 lease 过期恢复，grace period 待补
- [ ] admin readmodel providers 未实现（`admin_summary_registry` 为空注册）；R8/R9 余项
- [ ] FeatureSpec 与 composition.md §2.2 对齐（workflows/events/Cron/routers/ports 字段）待扩展
- [ ] 生产签名密钥加载器（env/file/KMS）未实现，现用 InMemorySigningKeyStore（container 与 CLI 均如此）
- [ ] SMTP adapter 配置由部署注入（`.env.example` 已含 `AIYA_SMTP_*`）；mailpit 验证容器已删除，集成测试在无 SMTP 端点时自动跳过
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
