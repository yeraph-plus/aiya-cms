# 质量、Compose 与发布规格

## 1. Compose profiles

- `runtime`：postgres、redis、mailpit、migrate、api、admin。
- `dev`：源码挂载的 api-dev/admin-dev，依赖仍使用 Compose 服务名。
- `test`：后端质量门、pytest、管理员质量门、Playwright。
- `review`：固定版本 OpenCodeReview 全仓扫描。
- `ops`：create-admin、OpenAPI dump/check 等一次性命令。

## 2. 必过门禁

- 后端：ruff check、ruff format --check、mypy、pip check、pytest 全绿、Alembic upgrade/downgrade/upgrade。
- 管理员：Biome、OpenAPI check、typecheck、unit、production build、依赖审计。
- 运行时：PG/Redis/Mailpit health、迁移、认证双令牌链路、真实管理员 E2E。
- OCR：Critical/High 为 0；Medium 必须修复或逐条登记接受后重跑。

## 3. 清洁与冻结

宿主机不保留 Python/Node 依赖、缓存、构建产物或本地工具设置；`.codegraph` 仅作为忽略的开发索引保留。全部门禁通过后创建初始源码提交和 `kernel-v0.1.0` 注释标签。
