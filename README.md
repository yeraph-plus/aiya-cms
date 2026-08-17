# aiya-cms

基于 FastAPI、SQLAlchemy、PostgreSQL 与 Vue 3 的模块化无头 CMS。规格事实来源从 [`context/README.md`](context/README.md) 进入，业务模块按显式组合独立演进。

## Compose 启动

宿主机只需要 Docker Compose；PostgreSQL/Redis 由 `compose.infra.yaml` 单独管理（生产可由 1panel 等面板接管），backend 镜像只通过拆分环境变量连接外部数据库。

```powershell
Copy-Item .env.example .env
docker compose -f compose.infra.yaml up -d
docker compose up -d --build
docker compose run --rm backend python -m inc.cli install --profile admin
```

默认发行只启动 `management_plane` 后端与非 root Nginx 管理员静态站：管理员入口为
<http://127.0.0.1:8080>，FastAPI 调试端口仅绑定 loopback 的
<http://127.0.0.1:8000>。Nginx 同源代理 `/api/`、`/oidc/` 和 Discovery；OIDC
私钥保存于 `oidc-key-data` 持久卷。

`install --profile admin` 一步完成迁移、points 种子、管理员 OIDC public client 与单一
超级管理员 bootstrap，不要求或登记用户站 secret/client；仅此入口可创建超级管理员。

Astro 用户站和完整 `cms` 产品组合涉及尚未闭合的 features，本轮不是生产发行的一部分。
仅用于继续开发时显式运行 `docker compose --profile site up --build`，并使用
`install --profile full` 登记用户站 confidential client；这不构成用户站生产验收。

管理员开发入口为 <http://127.0.0.1:5173>（在 `admin/` 运行 `npm run dev`），Mailpit 为 <http://127.0.0.1:8025>。停止并删除本项目容器和卷：

```powershell
docker compose down -v
docker compose -f compose.infra.yaml down -v
```

### 配置生效范围

- `AIYA_ISSUER` 是唯一的 OIDC issuer 配置；backend 和 Vite 管理员端都读取它，不再使用 `VITE_OIDC_ISSUER`。
- `AIYA_CORS_ORIGINS` 由 backend 读取，使用逗号分隔的精确 origin；`AIYA_CROS_ORIGINS` 是错误拼写，会在启动时拒绝。
- `AIYA_TRUSTED_PROXY_CIDRS` 控制哪些反代可以提供 `X-Forwarded-For`（单体生产镜像默认信任 loopback）；未命中时风控使用 TCP 对端地址。
- `AIYA_ENVIRONMENT=production` 强制 issuer 使用 HTTPS、cookie 使用 Secure，并禁止 CORS wildcard；开发环境使用 loopback HTTP。
- `.env` 改动需要重启 backend 和 Vite dev server；`AIYA_PUBLIC_BASE_URL` 改动后还要重新运行 `install`，使 OIDC redirect URI 与页面 origin 一致。
- OIDC Code + PKCE 依赖浏览器 Web Crypto。不能通过环境变量关闭 HTTPS 安全上下文要求；本地 HTTP 请使用 `localhost` 或 `127.0.0.1`，自定义 HTTP 域名需改用 HTTPS。

生产部署至少覆盖以下非 secret 值；数据库、Redis、S3 与管理员初始凭据仍由部署 secret 提供：

```dotenv
AIYA_ENVIRONMENT=production
AIYA_APP_PROFILE=management
AIYA_ISSUER=https://admin.example.com
AIYA_PUBLIC_BASE_URL=https://admin.example.com
AIYA_SECURE_COOKIES=true
AIYA_CORS_ORIGINS=https://admin.example.com
API_BIND_ADDRESS=127.0.0.1
ADMIN_BIND_ADDRESS=127.0.0.1
```

外层入口代理必须终止 TLS 并保留 `Host` 与 `X-Forwarded-Proto`；修改管理员 origin 后需重新构建 admin 镜像并重跑 `install --profile admin`，使 OIDC redirect URI 与静态 bundle 一致。

### 单体生产镜像

`.github/workflows/production-image.yml` 会先执行 `admin/` 的 `npm run build`，再构建并发布
`Dockerfile.production`。该镜像由 Nginx 托管 Vite `dist`，并把 `/api/`、`/oidc/`、Discovery
和 `/healthz` 反代到同一容器内 loopback 的 FastAPI；PostgreSQL、Redis 和 OIDC key volume
仍由部署环境提供。

发布到 `main` 或 `v*` tag 前，在 GitHub Repository Variables 配置
`AIYA_ISSUER` 与 `AIYA_PUBLIC_BASE_URL`（均为生产 HTTPS origin）；可选配置
`VITE_API_BASE_URL`。运行镜像示例：

```powershell
docker run -d --name aiya-cms --restart unless-stopped `
  --env-file .env -p 8080:8080 `
  -v aiya-oidc-key-data:/var/lib/aiya/oidc-keys `
  ghcr.io/OWNER/REPOSITORY:latest
```

也可以使用 [`compose.production.yaml`](compose.production.yaml)；它不读取 `env_file`，而是
在 `environment` 列表中显式传入管理面、PostgreSQL、Redis、OIDC、worker 和 S3 启动参数：
将 `AIYA_CMS_IMAGE` 设置为 Action 发布的 GHCR 镜像（未设置时使用本地
`aiya-cms:production`）。

生产 Compose 默认设置 `AIYA_AUTO_INSTALL=true`。容器首次连接空数据库时会自动执行
`install --profile admin`，生成的管理员密码只在首次创建成功时写入 Docker 日志；重启时
安装命令仍会幂等检查，但不会输出新的随机密码。Docker 日志属于敏感凭据载体，首次登录后
应立即修改密码并按部署平台策略清理/保护日志。若要手动执行安装，可设置
`AIYA_AUTO_INSTALL=false`。

```powershell
docker compose -f compose.infra.yaml up -d
docker compose -f compose.production.yaml up -d
docker compose -f compose.production.yaml run --rm app /opt/venv/bin/python -m inc.cli migrate
docker compose -f compose.production.yaml run --rm app /opt/venv/bin/python -m inc.cli install --profile admin
```

容器只对外暴露 Nginx 的 8080；生产外层入口仍负责 TLS。首次部署和迁移可以覆盖镜像的默认
supervisor 命令执行：

```powershell
docker run --rm --env-file .env -v aiya-oidc-key-data:/var/lib/aiya/oidc-keys `
  ghcr.io/OWNER/REPOSITORY:latest /opt/venv/bin/python -m inc.cli migrate
docker run --rm --env-file .env -v aiya-oidc-key-data:/var/lib/aiya/oidc-keys `
  ghcr.io/OWNER/REPOSITORY:latest /opt/venv/bin/python -m inc.cli install --profile admin
```

## 操作速查（backend 镜像内建一次性命令）

所有一次性操作都通过同一 backend 镜像执行：

| 操作 | 命令 |
| --- | --- |
| 应用数据库迁移 | `docker compose run --rm backend python -m inc.cli migrate` |
| 管理发行空库初始化（迁移 + 种子 + 超级管理员） | `docker compose run --rm backend python -m inc.cli install --profile admin` |
| 静态质量门（ruff / mypy / pip check） | `docker compose run --rm backend python -m inc.cli quality` |
| 运行测试套件（可追加 pytest 参数） | `docker compose run --rm backend python -m inc.cli test` |
| OpenAPI 快照漂移检查 | `docker compose run --rm backend python -m inc.cli openapi-check` |
| 迁移回退/重放校验 | `docker compose run --rm backend python -m inc.cli migration-check` |

生产连接必须显式设置 `AIYA_DATABASE_URL` 与 `AIYA_REDIS_URL`；拆分字段 `AIYA_PG_HOST/PORT/USER/PASSWORD/DATABASE`、`AIYA_REDIS_HOST/PORT/DB/PASSWORD` 仅用于开发或特殊非生产部署。发布验收中的真实 PostgreSQL/Redis 测试也读取这两个生产变量，缺失会直接失败。

## 开发与测试

```powershell
docker compose --profile dev up --build
docker compose run --rm backend python -m inc.cli test
docker compose run --rm backend python -m inc.cli quality
```

发布约束、健康检查、迁移和冻结门禁见 [`context/spec/quality-release.md`](context/spec/quality-release.md)；管理员专项验收见 [`context/admin dash spec (SPA)/admin.md`](<context/admin dash spec (SPA)/admin.md>)。
