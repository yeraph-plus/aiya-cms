# aiya-cms Admin

管理员 SPA 使用 Vue 3、TypeScript、Vite、Naive UI、Pinia、MSW 与 Vitest，作为同仓库 API 客户端维护。

```powershell
npm ci
npm run dev
npm run dev:mock
npm run check
npm run typecheck
npm run test:unit
npm run test:e2e
npm run build
```

默认入口为 <http://localhost:7000>，生产 Compose 入口为同一地址。OpenAPI 生成文件来自仓库根 `openapi.json`，提交前运行 `npm run check:api`。管理员产品与验收规格见 `context/spec/admin.md`，发布门禁见 `context/spec/quality-release.md`。

## Upstream

初始模板派生自 [doroudi/YummyAdmin](https://github.com/doroudi/YummyAdmin)，按 MIT License 使用；原始许可证保留在 `LICENSE`，来源记录在 `UPSTREAM.md`。
