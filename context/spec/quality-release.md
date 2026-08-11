# 质量、迁移、Compose 与发布规格

## 1. 开发顺序

每项行为固定遵循：

1. 更新 `context/spec/`。
2. 写能证明新合同尚未满足的失败测试。
3. 实现最小改动。
4. 跑所属层级测试和受影响集成测试。
5. 同步 migration、事件、OpenAPI、管理员生成类型和 Compose。
6. 从空环境复验发布门。

规格与实现出现差距时，必须由失败测试或明确的校验输出记录差距；不得在未通过相应发布门前宣称完成。

## 2. 测试层级

### 2.1 Architecture

必须静态或运行时验证：

- 四层 import 方向和 capability 无兄弟依赖。
- 跨能力无 ORM relationship/数据库外键/表修改。
- kernel 无业务词汇模型。
- Service/handler 无 Session，Repository 不泄漏 ORM。
- 无裸 SQL、无模型 JSONB、naive datetime、浮点金额。
- import 无注册/连接/线程副作用。
- 所有 key 显式注册、权限登记、validate/freeze。
- GET/HEAD 无业务写入和事件。

### 2.2 Kernel

- UoW commit/rollback、outbox/inbox 故障注入。
- workflow/activity crash、lease、retry、signal、shutdown 和版本演进。
- registry 顺序确定性、缺失/重复 fail-fast。
- secret redaction、Clock、错误和 diagnostics 只读性。

### 2.3 Capability

每项能力必须覆盖 DTO、Command/Query、权限、事务、并发、幂等、事件 schema、Port failure、diagnostics 和 migration owner。

专项门：

- OIDC：redirect/PKCE/nonce/code replay/issuer/audience/key rotation/refresh reuse/logout 负向测试和 OpenID conformance。
- Content：transition、定时发布重启/并发/取消、置顶分页、引用 purge。
- Taxonomy：single/multiple、OR/AND、page 无 taxonomy、孤儿只读诊断。
- Notification：provider timeout unknown、重试、模板 schema、敏感信息。
- Points：并发不超扣、幂等入账、reversal、负债和余额重算。
- Payments：验签、重放、乱序、金额匹配、captured/refund 和 timeout reconcile。

### 2.4 Feature

- post/page 声明不复制 capability 实现。
- check-in 同业务日并发只奖励一次。
- point purchase 在 webhook 重放和 worker 崩溃后只入账一次。
- 任何示例 workflow 未进入 production manifest 时无副作用。

### 2.5 HTTP/Admin

- error/page/auth/idempotency/version contract。
- 未启用 router 不存在，OpenAPI 不包含。
- OpenAPI snapshot/hash 和 TypeScript 类型无漂移。
- 管理员 format/lint/typecheck/unit/build。
- 真实 API Playwright 覆盖已完成核心路径。

## 3. PostgreSQL 与迁移门

- 首个重建版本只保留新 `0001_initial`。
- 从空 PostgreSQL `upgrade` 成功且 metadata/schema diff 为空。
- `upgrade -> downgrade -> upgrade` 成功；只有一个 deployable head。
- table owner 检查证明 revision 不修改兄弟 owner 表。
- 新基线发布后 revision 不可改写，后续按 owner 向前迁移。
- 测试 SQLite/in-memory 结果不能替代 PostgreSQL 验收。

## 4. Compose 组织

- `compose.infra.yaml`：只管理 PostgreSQL 和 Redis，暴露宿主端口。项目不做 All-in-One；生产部署由 1panel 等面板管理数据库，backend 只通过拆分环境变量（`AIYA_PG_HOST/PORT/USER/PASSWORD/DATABASE`、`AIYA_REDIS_HOST/PORT/DB/PASSWORD`）连接，构建内健康/初始化检查仅确认连接可用。
- `compose.yaml`：只包含 backend 镜像构建（`api` 运行服务 + `dev` 源码挂载）。migrate、install、quality、test、openapi-check、migration-check 全部内部化为 `inc.cli` 子命令，通过同一 backend 镜像 `docker compose run --rm backend python -m inc.cli <cmd>` 一次性执行。
- 一次性命令：`inc.cli migrate`（alembic upgrade head）、`inc.cli install`（迁移 + points 种子 + OIDC 客户端 + 单一超级管理员 bootstrap 一步完成）、`inc.cli quality`、`inc.cli test`、`inc.cli openapi-check`、`inc.cli migration-check`。

profile 名可在实现前调整，但最终必须有等价的单命令、可重复、无宿主依赖验收入口。

## 5. 建议命令门

```powershell
docker compose -f compose.infra.yaml up -d
docker compose run --rm backend python -m inc.cli migrate
docker compose run --rm backend python -m inc.cli install
docker compose run --rm backend python -m inc.cli quality
docker compose run --rm backend python -m inc.cli test
docker compose run --rm backend python -m inc.cli openapi-check
docker compose run --rm backend python -m inc.cli migration-check
```

命令名称以最终 Compose 为准；文档和 CI 必须同步。只运行 `docker compose config` 不代表数据库、Redis、worker 或业务链路健康。

## 6. 安全门

- 依赖漏洞扫描和 secret 扫描。
- CORS、CSP、cookie/CSRF、安全 header 和 TLS 生产配置测试。
- OIDC threat cases 与 conformance 通过。
- 支付 webhook、provider secret、日志 redaction 和请求大小/限流测试。
- 管理员 bundle 不含 token、secret、mock 和开发 endpoint。
- Critical/High 问题为 0；Medium 必须修复或逐条记录有期限的接受理由后重跑。

## 7. 空环境端到端门

从删除后的专用测试 volume 启动并验证：

1. PostgreSQL/Redis/通知开发 provider health。
2. `0001_initial` 迁移。
3. `install` 一步完成初始化（迁移 + 种子 + 单一超级管理员 bootstrap）；重复执行不产生第二个超级管理员。
4. OIDC discovery、Code + PKCE 登录、token refresh/revocation/logout。
5. 创建 post/page，page 无 taxonomy，定时发布与置顶分页。
6. check-in 一次性奖励。
7. payment sandbox webhook -> captured -> points credit -> refund reversal。
8. diagnostics/readmodels、OpenAPI 管理员页面。
9. 关闭并重启 worker 后无丢失/重复副作用。

## 8. 发布完成定义

- 新规格、实现、测试、迁移、OpenAPI、管理员端和 Compose 一致。
- `kernel_only`、`identity_provider`、完整 `cms` manifest 均能按预期启动。
- 未启用 capability 无运行副作用。
- 所有层级门和真实外部依赖健康检查通过。
- 没有临时 migration、多 head、旧 Demo endpoint/类型或兼容 shim。
- 发布证据记录实际命令和结果，不以文件存在、依赖已安装或配置解析成功替代运行验证。
