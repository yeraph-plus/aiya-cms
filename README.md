# aiya-cms

FastAPI、PostgreSQL、Vue 管理端与 Astro SSR 客户端组成的模块化无头 CMS。规格从 [`context/README.md`](context/README.md) 进入；`release` 是唯一可部署组合。

## 本地启动

```powershell
Copy-Item .env.example .env
docker compose -f compose.infra.yaml up -d
docker compose up -d --build
docker compose run --rm backend python -m inc.cli install
```

默认 Compose 同时启动 release backend、正式 Nginx 管理端与 Astro SSR 客户端。管理员入口为 <http://127.0.0.1:8080>，客户端入口为 Compose 配置的 site port，FastAPI 调试端口仅绑定 loopback。OIDC 私钥位于 `oidc-key-data` 持久卷，首次 install 生成 active key；删失或损坏 key material 会使应用启动失败。

release 包含管理面、公开内容浏览、用户注册/认证和 `/api/v1/me` 自助资料面。它不包含积分/会员购买、支付路由或支付 webhook。可选外部 provider 在启动时注册但不连接；运行时 settings 选择 SMTP/SMTP2GO、PayPal/Epay、S3。管理员 SPA 从 `openapi.admin.json` 生成类型，用户站从 `openapi.user.json` 生成类型，完整 `openapi.json` 仅用于系统验证。

## 操作命令

| 操作 | 命令 |
| --- | --- |
| 迁移 | `docker compose run --rm backend python -m inc.cli migrate` |
| 空库初始化 | `docker compose run --rm backend python -m inc.cli install` |
| 静态质量门 | `docker compose run --rm backend python -m inc.cli quality` |
| 测试 | `docker compose run --rm backend python -m inc.cli test` |
| OpenAPI 漂移检查 | `docker compose run --rm backend python -m inc.cli openapi-check` |
| 迁移回放检查 | `docker compose run --rm backend python -m inc.cli migration-check` |

生产必须显式设置 `AIYA_DATABASE_URL`、`AIYA_REDIS_URL`、`AIYA_ISSUER`、`AIYA_PUBLIC_BASE_URL` 与持久 `AIYA_OIDC_SIGNING_KEY_DIR`。完整门和空库约束见 [`context/spec/quality-release.md`](context/spec/quality-release.md)。
