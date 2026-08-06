# aiya-cms 开发总纲

`context/spec/` 是唯一规格事实来源。新增或改变行为时，先修改规格，再写失败测试，最后实现；不再维护 ADR、roadmap 或执行计划。

## 架构硬约束

- `inc/kernel` 不得导入 `inc/modules`；模块之间不得互相导入；`inc/api` 是唯一组合根。
- Service 不接收 Session，只经 Repository/UoW；Service 边界使用 Pydantic DTO；禁止裸 SQL。
- JSONB 字段必须有 Pydantic 模型；读路径不得写库或发事件；跨模块写入只经 EventBus。
- Pipeline、事件、Cron、内容类型和 Capability 必须显式注册并在启动时 fail-fast。
- 管理员端只消费 FastAPI OpenAPI；不引入自动发现式插件或自动路由系统。

## 目录与运行

`inc/kernel` 是冻结公共内核，`inc/modules` 是可替换业务模块，`inc/api` 是组合根，`admin` 是 Vue SPA，`alembic` 是迁移，`tests` 是测试，`context/spec` 是规格。

宿主机只需 Docker Compose：

```powershell
docker compose --profile runtime up -d --build
docker compose --profile ops run --rm create-admin --username admin --email admin@example.com
docker compose --profile test run --rm backend-quality
docker compose --profile test run --rm backend-test
docker compose --profile test run --rm admin-quality
docker compose --profile review run --rm opencode-review
```

质量门和冻结条件见 `context/spec/quality-release.md`；内核公开面见 `context/spec/kernel.md`。模块演进必须同步 API、迁移、OpenAPI 与管理员消费层，然后重建镜像。
