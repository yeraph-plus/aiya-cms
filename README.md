# aiya-cms

基于 FastAPI、SQLAlchemy、PostgreSQL 与 Vue 3 的模块化无头 CMS。内核公共契约冻结在 `context/spec/kernel.md`，业务模块可独立演进。

## Compose 启动

宿主机只需要 Docker Compose；PostgreSQL/Redis 由 `compose.infra.yaml` 单独管理（生产可由 1panel 等面板接管），backend 镜像只通过拆分环境变量连接外部数据库。

```powershell
Copy-Item .env.example .env
docker compose -f compose.infra.yaml up -d
docker compose up -d --build
docker compose run --rm backend python -m inc.cli install
```

`install` 一步完成迁移、points 种子、OIDC 客户端与单一超级管理员 bootstrap；仅此入口可创建超级管理员。

管理员开发入口为 <http://127.0.0.1:5173>（在 `admin/` 运行 `npm run dev`），Mailpit 为 <http://127.0.0.1:8025>。停止并删除本项目容器和卷：

```powershell
docker compose down -v
docker compose -f compose.infra.yaml down -v
```

### 配置生效范围

- `AIYA_ISSUER` 是唯一的 OIDC issuer 配置；backend 和 Vite 管理员端都读取它，不再使用 `VITE_OIDC_ISSUER`。
- `AIYA_CORS_ORIGINS` 由 backend 读取，使用逗号分隔的精确 origin；`AIYA_CROS_ORIGINS` 是错误拼写，会在启动时拒绝。
- `AIYA_ENVIRONMENT=production` 强制 issuer 使用 HTTPS、cookie 使用 Secure，并禁止 CORS wildcard；开发环境使用 loopback HTTP。
- `.env` 改动需要重启 backend 和 Vite dev server；`AIYA_PUBLIC_BASE_URL` 改动后还要重新运行 `install`，使 OIDC redirect URI 与页面 origin 一致。
- OIDC Code + PKCE 依赖浏览器 Web Crypto。不能通过环境变量关闭 HTTPS 安全上下文要求；本地 HTTP 请使用 `localhost` 或 `127.0.0.1`，自定义 HTTP 域名需改用 HTTPS。

## 操作速查（backend 镜像内建一次性命令）

所有一次性操作都通过同一 backend 镜像执行：

| 操作 | 命令 |
| --- | --- |
| 应用数据库迁移 | `docker compose run --rm backend python -m inc.cli migrate` |
| 空库初始化（迁移 + 种子 + 超级管理员） | `docker compose run --rm backend python -m inc.cli install` |
| 静态质量门（ruff / mypy / pip check） | `docker compose run --rm backend python -m inc.cli quality` |
| 运行测试套件（可追加 pytest 参数） | `docker compose run --rm backend python -m inc.cli test` |
| OpenAPI 快照漂移检查 | `docker compose run --rm backend python -m inc.cli openapi-check` |
| 迁移回退/重放校验 | `docker compose run --rm backend python -m inc.cli migration-check` |

连接参数为拆分字段：`AIYA_PG_HOST/PORT/USER/PASSWORD/DATABASE`、`AIYA_REDIS_HOST/PORT/DB/PASSWORD`；显式 `AIYA_DATABASE_URL`/`AIYA_REDIS_URL` 覆盖优先（SQLite 测试与特殊部署）。

## 开发与测试

```powershell
docker compose --profile dev up --build
docker compose run --rm backend python -m inc.cli test
docker compose run --rm backend python -m inc.cli quality
```

发布约束、健康检查、迁移和冻结门禁见 [`context/spec/quality-release.md`](context/spec/quality-release.md)；管理员专项验收见 [`context/spec/admin.md`](context/spec/admin.md)。
