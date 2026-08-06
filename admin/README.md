# aiya-cms Admin

管理员 SPA 与 aiya-cms 后端在同一仓库、同一版本中维护。技术栈为 Vue 3、TypeScript、Vite、Naive UI、UnoCSS、Pinia、MSW 和 Vitest。

## Commands

```powershell
npm ci
npm run dev
npm run dev:mock
npm run check
npm run typecheck
npm run test:unit
npm run test:e2e
npm run build
npm run generate:api
npm run check:api
```

开发服务器默认监听 <http://localhost:7000>。`npm run dev` 通过同源 `/api`
代理访问真实后端 `http://localhost:8000`；`npm run dev:mock` 显式启用 MSW，使用账号
`admin` / `admin1234`。访问令牌只保存在内存，刷新令牌由后端通过
`HttpOnly` Cookie 管理。

真实浏览器联调需要先启动后端和数据库，再执行
`$env:AIYA_E2E_REAL='true'; npm run test:e2e:real`。

`src/common/api/generated/api.ts` 必须由仓库根冻结的 `openapi.json` 生成；提交前运行
`npm run check:api` 检查客户端是否过期。管理员端规格见
`context/admin/00-overview.md`，A0/A1 执行计划见
`context/admin/01-a0-a1-plan.md`。

## Upstream

初始模板派生自 [doroudi/YummyAdmin](https://github.com/doroudi/YummyAdmin)，按 MIT License 使用。原始许可文本保留在 `LICENSE`，来源详情见 `UPSTREAM.md`。
