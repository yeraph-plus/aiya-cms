# Admin / 总览（00-overview）

## 1. 设计目的

管理员 SPA 是 aiya-cms 的同仓库操作界面，负责用户、角色、内容、taxonomy、评论、审计、设置和任务等管理工作。A0 基于 YummyAdmin 建立可构建基线，A1 将模板收敛为 aiya-cms 应用壳；具体业务页面随对应后端里程碑按契约交付。

A0/A1 的状态、执行批次、双轨同步点与完成定义见 [01-a0-a1-plan.md](01-a0-a1-plan.md)。 M1/A1 总体执行编排见 [../m1-a1-plan.md](../m1-a1-plan.md)。

非目标：不承载公开站点前台；不在浏览器复刻后端授权；不直接依赖 Python 源码；不建立自动发现式前端插件系统。

## 2. 技术基线

| 项 | 决策 |
|---|---|
| 运行时 | Node.js 24 |
| 包管理 | npm + `package-lock.json`，CI 使用 `npm ci` |
| 框架 | Vue 3 + TypeScript + Vite |
| UI / 样式 | Naive UI + UnoCSS + Sass |
| 状态 | Pinia 仅管理会话与客户端状态；服务端数据在 A1 统一 API 层管理 |
| 路由 | Vue Router + 文件路由 |
| i18n | vue-i18n，默认 `zh-CN` |
| Mock | MSW，仅显式 mocking 模式启用 |
| 质量门 | Biome + vue-tsc + Vitest + Vite build |

兼容例外：`vue-tsc 3.3.9` 实际仍加载 `typescript/lib/tsc`，与 TypeScript 7 的 exports 不兼容；A0 固定 TypeScript 6.0.3（6.x 最新稳定版），待 vue-tsc 发布兼容版本后再恢复 latest。

## 3. 目录边界

```text
admin/
  public/          # 静态资源与 MSW worker
  scripts/         # 本项目维护脚本
  src/
    common/api/    # A1 统一 HTTP、生成客户端适配、错误映射
    components/    # 可复用管理端组件
    layouts/       # 管理端布局
    locales/       # i18n
    mocks/         # 显式 mock 模式 handler
    pages/         # 路由页面
    store/         # 会话与纯客户端状态
  package.json
  package-lock.json
```

`admin/` 不保留上游独立仓库元数据，不设置独立版本发布。上游 MIT License 必须保留。

## 4. API 契约

- 基础地址由 `VITE_API_URL` 提供，默认开发目标为本地 FastAPI `/api/v1`。
- A1 起 TypeScript DTO 与客户端从 FastAPI OpenAPI 生成；生成文件不可手工编辑。
- 后端错误统一映射 `code/http_status/message/request_id`，页面逻辑优先判断稳定错误码，不匹配 message 文本。
- `/auth/me` 返回的 capabilities 驱动路由与操作可见性；所有敏感请求仍由后端 `require_capability` 校验。
- refresh token 存储、CORS 与 CSRF 是安全决策：见 [ADR-0013](../adr/0013-browser-token-storage-cors-csrf.md)（httpOnly Cookie refresh + access 内存）。request_id 传播见 [ADR-0014](../adr/0014-request-id-propagation.md)，健康检查契约见 [ADR-0015](../adr/0015-health-check-contract.md)。

## 5. A0 验收边界

状态：已完成并封板（2026-08-03）。

- 上游模板归入 `admin/`，保留 MIT License，移除独立仓库与上游发布配置。
- npm 是唯一包管理器，`npm ci` 可从锁文件复现安装。
- 直接与开发依赖更新到 npm registry 最新稳定兼容版，所有例外均有证据登记，类型与构建兼容问题已解决。
- `npm run check`、`npm run typecheck`、`npm run test:unit`、`npm run build` 全绿。
- `npm run dev` 启动正常，主要页面在桌面与移动视口无阻断性错误。

## 6. A1 验收边界

状态：实现与真实运行时验收完成（2026-08-05）；mock/real 桌面与移动浏览器验收均已通过。

- aiya-cms 品牌、中文默认语言和管理导航完成；无 YummyAdmin 赞助、商城演示或上游部署入口。
- 正常 development 不启动 MSW；`dev:mock` 明确启用。
- 登录、me、退出、401 单飞刷新、超时/取消、Capability 守卫和统一错误映射具备单元测试。
- mock 模式完成登录→me→受限路由→refresh→logout 链路；Playwright 已覆盖 Chromium 桌面与移动视口。
- 真实模式通过同源 `/api` 代理访问 FastAPI；`/api/v1/health`、真实认证链路与 PostgreSQL/Redis 运行时验收已通过。

应用壳精简批次（语言、主题偏好和模板遗留入口）见 [02-shell-cleanup.md](02-shell-cleanup.md)。

A2 操作面板与管理闭环见 [03-a2-operation-panels.md](03-a2-operation-panels.md)。

## 7. 未决事项

- OpenAPI 客户端生成器已登记：**openapi-typescript** + 原生 fetch 适配（G0 决策，2026-08-04），生成目录 `src/common/api/generated/`，详见 [01-a0-a1-plan.md](01-a0-a1-plan.md) A1.2。
- 动态内容类型的 JSON Schema 与管理端 UI Schema 契约随 A2 另写规格。
- Playwright 已加入 `admin/test:e2e`（mock）与 `admin/test:e2e:real`（真实后端）质量门。
