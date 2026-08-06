# 管理员轨 A0/A1 执行计划

> 状态基线：A0 已完成并封板；A1 代码与真实运行时联调均完成（2026-08-05）。

> M1/A1 双轨批次、同步门和首轮提交顺序见 [../m1-a1-plan.md](../m1-a1-plan.md)。

## 1. 范围与状态

| 里程碑 | 状态 | 目标 | 后端依赖 |
|---|---|---|---|
| A0 模板基线 | 已完成（2026-08-03） | 将 YummyAdmin 收归同仓库，形成可复现、可检查、可测试、可构建的 npm 基线 | 无 |
| A1 应用壳 | 实现与真实运行时验收完成（2026-08-05） | 将通用模板收敛为 aiya-cms 管理壳，接入 OpenAPI、认证、Capability 与健康检查 | FastAPI、PostgreSQL、Redis 已验收 |

A0 只解决技术基线，不计入 aiya-cms 业务功能。A1 只交付管理应用壳，不提前实现内容、taxonomy、评论等 A2 页面。

## 2. A0 模板基线（已完成）

### 2.1 已交付

- [x] 将 [doroudi/YummyAdmin](https://github.com/doroudi/YummyAdmin) 导入 `admin/`，移除嵌套仓库及独立发布边界。
- [x] 保留 MIT License 与 `UPSTREAM.md` 来源记录，移除上游 CI、Netlify、赞助入口和 pnpm 限制。
- [x] 包管理器统一为 npm，仅保留 `package-lock.json`，使用 `npm ci` 复现安装。
- [x] 依赖升级到当前最新稳定兼容集合；TypeScript 6.0.3 是已登记的兼容例外。
- [x] 固化 Biome、vue-tsc、Vitest、Vite production build 四项质量门。
- [x] 移除离线环境会阻塞启动的远程字体加载，开发服务器可稳定访问。

### 2.2 封板证据

在 `admin/` 执行：

```powershell
npm ci
npm run check
npm run typecheck
npm run test:unit
npm run build
npm audit
```

封板结果：安装可复现，四项质量门全绿，单元测试通过，production build 成功，`npm audit` 为 0 vulnerabilities。

### 2.3 封板规则

- A1 从当前 `package-lock.json` 与质量门结果开始，不重新导入或同步上游模板。
- A0 后续只接受依赖维护、构建修复与安全修复；品牌、契约和业务变更归入 A1+。
- TypeScript 仅在 `vue-tsc` 明确兼容 TypeScript 7 后升级，升级时必须重跑全部管理员端质量门。

## 3. A1 管理员端应用壳（实现完成）

### 3.1 A1.1 产品壳收敛

目标：让首屏、导航和基础交互成为 aiya-cms 管理端，而不是模板演示站。

- [x] 替换产品名、标题、图标和基础元信息为 aiya-cms。
- [x] 默认语言切换为 `zh-CN`，保留明确的 fallback 语言。
- [x] 按用户与权限、内容、taxonomy、评论、审计、设置、任务建立导航信息架构，并按 Capability 过滤。
- [x] 移除商城、赞助、上游部署入口和无关演示路由；保留可复用布局及 MSW 基础设施。
- [x] 为应用启动、默认语言、导航可见性和 404/403 基础状态增加单元测试。

退出条件：无上游业务入口；刷新任一保留路由可恢复；桌面与移动视口均可完成导航。

### 3.2 A1.2 API 与 OpenAPI 契约

目标：前端只通过版本化 HTTP/OpenAPI 契约依赖后端，不长期手写重复 DTO。

**OpenAPI 生成器（G0 已登记，2026-08-04）：**

- 工具：`openapi-typescript`（生成纯类型）+ 原生 `fetch` 适配层（统一 HTTP 服务），不引入 axios/运行时客户端运行时依赖。
- 版本：实际安装时钉版并记入 `admin/package.json` devDependencies；此处登记选择，G3 冻结 OpenAPI 后锁版本。
- 生成目录：`admin/src/common/api/generated/`，生成文件只读、禁止手工编辑。
- 生成命令：`npm run generate:api`，过期检查：`npm run check:api`。
- 更新规则：后端 OpenAPI 变更后先重生成，再更新消费方；质量门以「生成物过期检查」兜底——后端 schema 哈希变更且未重新生成时质量门失败。
- 适配：`VITE_API_URL` base URL、超时/取消、request_id（见 [ADR-0014](../adr/0014-request-id-propagation.md)）、204 处理、错误体解析为 `AppError(code/http_status/message/request_id)`（与 [ADR-0013](../adr/0013-browser-token-storage-cors-csrf.md) 会话衔接）。

执行项：

- [x] 从 M1 的冻结 OpenAPI 文档生成 TypeScript 类型/客户端；生成文件禁止手工编辑。
- [x] 建立统一 API 服务，处理 `VITE_API_URL`、超时、取消、请求标识和响应解析。
- [x] 将后端错误统一映射为 `ApiError(code/http_status/message/request_id)`，页面只依赖稳定错误码。
- [x] 增加生成物过期检查，OpenAPI 变更后未重新生成时质量门必须失败。

退出条件：至少一个健康检查请求使用生成客户端；无手写重复后端 DTO；错误映射具备单元测试。

### 3.3 A1.3 会话与 Capability

目标：形成可复用的登录会话壳和前端交互授权层。

- access/refresh 存储、CORS、CSRF 与注销策略已定：见 [ADR-0013](../adr/0013-browser-token-storage-cors-csrf.md)（httpOnly Cookie refresh + access 内存 + SameSite=Strict）。
- [x] 实现登录、`/auth/me`、退出和会话恢复；Pinia 只保存会话与纯客户端状态。
- [x] 实现 401 单飞刷新、失败请求最多重放一次、刷新失败清理会话，禁止重试循环。
- [x] 使用 `/auth/me` 的 capabilities 驱动路由守卫、导航和操作可见性，并提供 401/403/503 状态页。
- 后端 `require_capability` 始终是授权权威；前端隐藏元素不作为安全边界。

退出条件：mock 模式通过“登录 -> me -> 受限路由 -> 刷新恢复 -> 退出”链路，并覆盖并发 401 场景。

### 3.4 A1.4 真实联调与验收

目标：将 mock 契约替换为 M1 的真实 FastAPI + PostgreSQL 链路。

- [x] `npm run dev` 默认请求 FastAPI；仅 `npm run dev:mock` 注册显式 auth/health MSW handlers。
- [x] 增加后端、数据库、Redis 状态可见的健康检查页，但不在 GET 路径触发业务写入。
- [x] M1 auth/api 就绪后移除旧模板 mock handlers，避免 mock 与真实接口漂移。
- [x] 使用 Playwright 覆盖登录、受限路由、刷新恢复、退出并验证 Chromium 桌面与移动视口。
- [x] 生成客户端、会话单测、管理员 check/typecheck/unit/build 全绿；真实 FastAPI + PostgreSQL + Redis 运行时联调通过。

退出条件：真实环境通过“登录 -> me -> 受限路由 -> 退出”链路；无静默 mock；管理员端全部质量门全绿。

## 4. 双轨同步点

| A1 交付 | 可独立推进 | 需要 M1 提供 | 集成判定 |
|---|---|---|---|
| A1.1 产品壳 | 是 | 无 | 视觉、路由、i18n 单测通过 |
| A1.2 API 契约 | 部分 | 冻结的 `/api/v1` OpenAPI 与错误模型 | 生成客户端调用真实 health 接口 |
| A1.3 会话授权 | mock 可推进 | auth/me/refresh/logout 与 Capability 契约 | mock 与真实响应使用同一生成类型 |
| A1.4 真实联调 | 否 | FastAPI、PostgreSQL、Redis 可用 | 真实认证链路与 Playwright 全绿 |

同步纪律：M1 契约先改后端规格与 OpenAPI，再更新生成客户端和 A1 测试；A1 不以临时手写 DTO 绕过尚未确定的后端契约。

## 5. A1 完成定义

- [x] aiya-cms 品牌、中文默认语言、管理导航和错误状态完成。
- [x] 正常开发模式不启用 MSW，mock 模式可独立演示完整会话链路。
- [x] API 类型/客户端由 OpenAPI 生成，统一错误映射与过期检查生效。
- [x] 登录、me、刷新、退出和 Capability 守卫具备单元测试。
- [x] Playwright 桌面/移动 mock 验收用例通过；真实 FastAPI + PostgreSQL + Redis 登录、刷新恢复、退出验收通过。
- [x] `npm ci` 依赖锁已更新，check、typecheck、unit test、build 与 mock/real E2E 全绿。
