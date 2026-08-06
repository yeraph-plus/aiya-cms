# ADR-0012: 同仓库集成 YummyAdmin 管理员 SPA

- 状态: accepted
- 日期: 2026-08-03
- 决策者: 项目所有者 + AI 协作
- 关联: [architecture/00-overview.md](../architecture/00-overview.md)、[admin/00-overview.md](../admin/00-overview.md)、[roadmap.md](../roadmap.md)

## 背景

项目需要与后端同步建设可用的管理员中台。自行从零搭建布局、主题、表格、图表、i18n 和 mock 基础设施会延迟首个垂直闭环；doroudi/YummyAdmin 已提供 Vue 3 + TypeScript + Vite + Naive UI 的完整 SPA 模板，并采用 MIT License。

项目所有者决定管理员端与后端在同一仓库、同一版本和同一质量门下维护，不建立独立前端仓库。上游源码仅作为起始模板，导入后由 aiya-cms 直接演进。

## 决策

1. 管理员 SPA 固定放置于仓库 `admin/`，与 `inc/`、`context/`、`tests/` 同级；不保留嵌套 `.git`，不作为 submodule。
2. 基线派生自 [doroudi/YummyAdmin](https://github.com/doroudi/YummyAdmin)，保留其 MIT License 和来源记录；移除与本项目无关的上游 CI、Netlify、赞助入口和发布配置。
3. Node.js 基线为 24，包管理器统一为 npm。仓库只保留 `admin/package-lock.json`，禁止提交 pnpm/yarn/bun 锁文件；`npm ci` 是 CI 与复现安装入口。
4. A0 将直接依赖与开发依赖升级到 npm registry 当时的最新稳定兼容版本，并修复破坏性升级。若两个 latest 版本无法组成可运行集合，必须在管理员规格登记证据并固定最新兼容版本。`package-lock.json` 锁定完整依赖图，后续升级走显式变更与质量门。
5. 管理员端只通过 `/api/v1` HTTP/OpenAPI 契约访问后端，禁止导入 Python 源码。A1 起 API 类型与客户端由 FastAPI OpenAPI 生成，禁止长期手写重复 DTO。
6. 后端 Capability 是授权权威。前端路由守卫和按钮显隐只改善交互，不能替代后端鉴权。
7. MSW 仅在显式 mocking 模式启用；正常 development 模式请求本地 FastAPI，避免 mock 掩盖契约漂移。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| 独立前端仓库 | 发布和权限可独立 | 契约、版本、CI 与文档容易漂移 | 当前单一产品与团队不需要拆分 |
| Git submodule 跟踪上游 | 可继续拉取上游更新 | 本地定制与上游演进冲突，协作复杂 | 模板仅作起点，不持续追随上游 |
| 从零搭建 Vue 管理端 | 代码完全贴合业务 | 重复建设基础 UI，延迟业务验证 | YummyAdmin 已覆盖所需基础设施 |
| 继续使用 pnpm | 安装快、上游原生支持 | 与所有者指定 npm 冲突 | 包管理器统一为 npm |

## 后果

### 正面

- 后端与管理员端在一个变更集中同步审查、测试和发布。
- 直接获得成熟布局、响应式界面、i18n、MSW、表格和图表能力。
- OpenAPI 生成客户端减少 Python DTO 与 TypeScript 类型漂移。

### 负面 / 代价

- 首次依赖大版本升级需要一次性处理模板兼容问题。
- 导入的演示业务较多，A1 必须明确清理，避免模板模型污染 CMS 领域。
- 单仓库质量门耗时增加，需要后续按路径做 CI 缓存和选择性执行。

### 逃生门

- 若管理员端未来需要独立发布，可在保持 OpenAPI 契约不变的前提下拆分仓库；拆分前必须新增 ADR，不改变后端分层边界。
