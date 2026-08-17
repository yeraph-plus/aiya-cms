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
- Content：transition、定时发布重启/并发/取消、置顶分页、引用 purge；Markdown CRLF 规范化、UTF-8 byte 上限、profile allowlist、链接 scheme、asset reference 与发布门；slug 的 CJK/空 stem/长度 fixture、并发重名重试、创建后不可变、公开 lookup 与 UUID/数值短码隔离。
- Taxonomy：single/multiple、OR/AND、page 无 taxonomy、孤儿只读诊断。
- Community：discussion + 首帖原子性、reply 并发序号/幂等、审核/锁定/隐藏/归档、primary/secondary tag 约束、`latest/top/newest/relevance` 稳定分页，以及中文/ASCII 搜索、隐藏正文零泄露和投影重建。
- Notification：provider timeout unknown、重试、模板 schema、敏感信息。
- Points：并发不超扣、幂等入账、reversal、负债和余额重算。
- Payments：验签、重放、乱序、金额匹配、captured/refund 和 timeout reconcile。

### 2.4 Feature

- `auth` 的注册、邮箱验证和密码找回流程只经 capability public Command/Query/Port 编排；HTTP router 不直接调用 identity/access/notification 的领域命令。
- `user_center`/post/page 声明不复制或访问 capability ORM/Repository。
- `user_center` 中 check-in 同业务日并发只奖励一次。
- `user_center` 中 point/membership purchase 在 webhook 重放和 worker 崩溃后只入账/订阅一次。
- post 独占用户 engagement/comments 组装；page 无 taxonomy/engagement/comments。
- community 作为独立 capability 直接拥有 discussion/post/tag/search，不注册同名 feature，也不复用 content/taxonomy/comments 表。
- post/page 通过公开 `ContentPublicationPolicy`/assets Port 校验 Markdown asset ready，不发生 content -> assets/feature 反向依赖；空 body/excerpt 不能 submit/schedule/publish。
- 旧四个独立业务 feature 不进入 production manifest，旧用户路由不进入 OpenAPI。
- 任何示例 workflow 未进入 production manifest 时无副作用。

### 2.5 HTTP/Frontends

- error/page/auth/idempotency/version contract。
- `/admin` capability CRUD router 不导入 ORM 或直接使用 UoW；仅跨能力多步业务通过 feature gateway。
- 未启用 router 不存在，OpenAPI 不包含。
- 完整/用户 OpenAPI snapshot/hash 和两端生成 TypeScript 类型无漂移；用户投影不含 admin/webhook。
- 管理员 format/lint/typecheck/unit/build。
- 管理员 Community 菜单只调用 `/api/v1/admin/community/**`；Discussions/Tags 两个工作台的权限、抽屉/对话框、国际化和生成 DTO 合同通过，且不导入 content/taxonomy adapter。
- Astro 用户站 format/lint/typecheck/unit/build，server-only API/auth 模块不进入客户端 bundle。
- Astro 基础壳合同覆盖 route manifest、受保护路由与安全 return path、`zh-CN`/`en` 同名路由、缺失翻译、`system|light|dark` allowlist、键盘/焦点语义和无 JavaScript 基础导航；用户站不得引入 Vue Router、Pinia 或管理员 PrimeVue 运行时代码。
- OIDC BFF 单元测试覆盖 Discovery、PKCE S256、state/nonce、callback session rotation、过期 transaction、refresh 单飞、revocation/logout、本地 session 销毁与安全错误；token、verifier 和 client secret 不得出现在安全 session projection、HTML、Vue props 或日志快照。
- 用户 API server adapter 使用生成 paths，自动附加 request ID/Bearer，在 401 时最多刷新并重放一次；合同测试拒绝浏览器 bundle 导入 server-only auth/API 模块。
- backend Markdown policy、共享 `packages/markdown`、管理员预览和 Astro SSR 使用同一恶意语料与 golden fixture；覆盖 raw HTML/MDX/directive、危险 scheme、控制字符、Unicode/byte 边界、asset reference、确定性 heading ID 和 sanitize allowlist。
- API/数据库/事件/OpenAPI snapshot 均不包含派生 HTML；渲染输出不执行脚本、代码块或 embed，不覆盖受保护 DOM ID，不抓取远程资源。
- renderer/profile/sanitize 版本进入缓存键；版本变化会失效旧 HTML cache，且可从 Markdown 原文确定性重建。
- Astro SEO 合同测试覆盖 canonical/head/JSON-LD 转义、published/indexable sitemap、稳定分片、生产/非生产 robots、缓存失效，以及 share image 不使用短期 signed URL。
- 真实 API Playwright 覆盖已完成核心路径。

## 3. PostgreSQL 与迁移门

- 首个重建版本只保留新 `0001_initial`。
- 从空 PostgreSQL `upgrade` 成功且 metadata/schema diff 为空。
- `upgrade -> downgrade -> upgrade` 成功；只有一个 deployable head。
- table owner 检查证明 revision 不修改兄弟 owner 表。
- 新基线发布后 revision 不可改写，后续按 owner 向前迁移。
- 测试 SQLite/in-memory 结果不能替代 PostgreSQL 验收。

## 4. Compose 组织

- `compose.infra.yaml`：只管理 PostgreSQL 和 Redis，暴露宿主端口。应用发行可选择 `Dockerfile.production` 的单体镜像（Nginx 托管 SPA 并反代同容器内的 FastAPI）；数据库与 Redis 仍不进入应用镜像，由 1panel 等面板管理，生产 backend 必须通过显式 `AIYA_DATABASE_URL` 与 `AIYA_REDIS_URL` 连接（拆分 `AIYA_PG_*`/`AIYA_REDIS_*` 字段仅供开发或特殊非生产部署）。
- `compose.yaml`：默认只启动 `management_plane` backend 与 unprivileged Nginx 管理员静态服务；backend/管理员端口默认只绑定宿主 loopback，外层入口代理负责 TLS。Astro Node standalone 服务保留在显式 `site` profile，在完整产品 feature 和用户站端到端门完成前不得进入默认生产拓扑。
- 单体镜像仍只暴露 Nginx 的 8080 端口；FastAPI 必须监听容器内 loopback，Nginx 负责 `/api/**`、`/oidc/**`、Discovery 和 `/healthz` 代理。`supervisord` 只负责同容器内两个进程的生命周期，不改变 API 的组合根或业务边界。
- `compose.production.yaml` 是单体镜像的运行配置事实源：使用 `environment` 列表显式注入管理面、数据库、Redis、OIDC、worker 和 S3 参数，不使用 `env_file`；`Dockerfile.production` 不写入运行时 `ENV`，同一镜像可跨环境迁移。
- `compose.yaml` 与 `compose.production.yaml` 都必须显式注入 `AIYA_DATABASE_URL`、`AIYA_REDIS_URL`；缺失时 Compose 配置解析失败。发布验收测试同样读取这两个生产变量，缺失时测试失败而不是跳过。
- 单体镜像 entrypoint 在 `AIYA_AUTO_INSTALL=true` 且即将启动 supervisor 时调用既有 `inc.cli install --profile admin`；该命令必须保持幂等，只有空库首次生成的管理员密码允许出现在 Docker 日志，应用 FastAPI lifespan 不直接执行 bootstrap。
- backend 是唯一写实例并在同一进程内持有唯一 worker runtime；生产不得使用 Uvicorn 多 worker，也不得复制 backend service。管理员静态服务可以独立扩容。
- 一次性命令：`inc.cli migrate`（alembic upgrade head）、`inc.cli install --profile admin`（迁移 + points 种子 + 管理员 OIDC public client + 单一超级管理员，不要求或登记用户站 secret/client）、完整产品 `inc.cli install --profile full`、`inc.cli quality`、`inc.cli test`、`inc.cli openapi-check`、`inc.cli migration-check`。

profile 名可在实现前调整，但最终必须有等价的单命令、可重复、无宿主依赖验收入口。

## 5. 建议命令门

```powershell
docker compose -f compose.infra.yaml up -d
docker compose run --rm backend python -m inc.cli migrate
docker compose run --rm backend python -m inc.cli install --profile admin
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
- 用户站 HTML、Vue props、浏览器存储和客户端 bundle 不含 access/refresh token、OIDC client secret 或 server-only API 配置。
- Critical/High 问题为 0；Medium 必须修复或逐条记录有期限的接受理由后重跑。

## 7. 空环境端到端门

从删除后的专用测试 volume 启动并验证：

1. PostgreSQL/Redis/通知开发 provider health。
2. `0001_initial` 迁移；community 表、排序索引、`pg_trgm` 与搜索索引可在空 PostgreSQL 重放。
3. `install` 一步完成初始化（迁移 + 种子 + 单一超级管理员 bootstrap）；重复执行不产生第二个超级管理员。
   install 同时登记管理员 public client 与用户站 confidential client；用户站 secret 只写入部署 secret，不进入日志或命令结果历史。
4. 管理员 public-client 与 Astro confidential-BFF 两条 OIDC Code + PKCE 登录、refresh/revocation/logout 路径。
5. 不同二级域名下 Astro SSR 读取 post/page/community discussion 与 Tags；禁用 JavaScript 仍可阅读/浏览，page 无 taxonomy/engagement/comments；canonical、head、JSON-LD、`robots.txt` 和 sitemap 来自用户站 origin。
6. user_center check-in 一次性奖励、积分/会员摘要和本人购买读取。
7. post 显式 view、like/rating 与评论提交/审核可见性。
8. community 创建 discussion/首帖、并发 reply、审核/锁定/归档、Tags 管理，以及 `latest/top/newest/relevance` + 中文搜索；隐藏正文不可检索。
9. payment sandbox webhook -> point/membership purchase captured -> credit/subscription；point refund reversal。
10. Redis session 过期/注销、CORS/CSRF 和 token 不落浏览器验证。
11. sitemap 只包含 published/indexable post/page，非生产 robots 强制禁止索引，SEO media URL 稳定且无短期 signed URL。
12. diagnostics/readmodels、完整/用户 OpenAPI 与两端生成 client。
13. 关闭并重启 worker 后无丢失/重复副作用。

## 8. 发布完成定义

### 8.1 管理面上线（本轮）

- `management_plane` 能在 production settings 下 fail-fast 构建和启动，不绑定开发 payment provider，不挂载 `/api/v1/me` 或普通用户业务路由。
- 管理面 notification challenge 只能通过受保护的内部投递 workflow 发送，token 不进入响应、事件、日志或管理员 DTO；SMTP/Mailpit 投递、重试和终态清理通过真实依赖验收。
- 管理员 OIDC public client、`/api/v1/admin/session`、已装配 `/api/v1/admin/**` 路由、OpenAPI/生成类型和 SPA 调用一致；陈旧或未装配 permission 不进入 session capability 集。
- 管理员 Nginx 镜像以非 root 用户运行，静态缓存、安全 header、SPA fallback 与同源 API/OIDC 代理合同通过；生产 bundle 不含 mock、secret、sourcemap 或开发 endpoint。
- 空 PostgreSQL 执行 `install --profile admin`、重复执行、登录、权限负向、管理核心路径、backend readiness 和容器重启门通过。
- 只把本节结果称为“管理面上线”；不得据此宣称完整 CMS 产品或用户站发布完成。

### 8.2 完整产品发布（后续）

- 新规格、实现、测试、迁移、完整/用户 OpenAPI、管理员端、用户站和 Compose 一致。
- `kernel_only`、`identity_provider`、完整 `cms` manifest 均能按预期启动。
- 未启用 capability 无运行副作用。
- 所有层级门和真实外部依赖健康检查通过。
- 没有临时 migration、多 head、旧 Demo endpoint/类型或兼容 shim。
- 发布证据记录实际命令和结果，不以文件存在、依赖已安装或配置解析成功替代运行验证。
