# aiya-cms

基于 FastAPI、SQLAlchemy、PostgreSQL 与 Vue 3 的模块化无头 CMS。内核公共契约冻结在 `context/spec/kernel.md`，业务模块可独立演进。

## Compose 启动

宿主机只需要 Docker Compose：

```powershell
Copy-Item .env.example .env
docker compose --profile runtime up -d --build
docker compose --profile ops run --rm create-admin --username admin --email admin@example.com
```

管理员入口为 <http://localhost:7000>，Mailpit 为 <http://localhost:8025>。停止并删除本项目容器和卷：

```powershell
docker compose down -v
```

## 开发与测试

```powershell
docker compose --profile dev up --build
docker compose --profile test run --rm backend-quality
docker compose --profile test run --rm backend-test
docker compose --profile test run --rm admin-quality
docker compose --profile test run --rm admin-e2e
```

发布审查使用 `docker compose --profile review run --rm opencode-review`。运行约束、健康检查、迁移和冻结门禁见 [`context/spec/quality-release.md`](context/spec/quality-release.md)；管理员专项验收见 [`context/spec/admin.md`](context/spec/admin.md)。
