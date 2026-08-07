# 管理员端规格

## 1. 定位

`admin/` 是独立 Vue SPA，只通过 HTTP/OpenAPI 使用系统能力。它不是后端插件宿主，不读取 Python 源码、数据库、migration manifest 或 capability 内部注册表。

保留 YummyAdmin 的 MIT 许可证 `admin/LICENSE` 和来源说明 `admin/UPSTREAM.md`；重构业务页面不得移除归属信息。

界面基座为 Sakai Vue UI kit（MIT），组件与页面清单见 `admin-uikit.md`。

## 2. 契约

- 所有 API 类型从根 OpenAPI snapshot 生成。
- API adapter 引用生成的 paths/operations/components，不维护平行 TypeScript DTO。
- 不允许 `any`/`unknown` payload、手工复制 Page/Error/业务 schema 或静默吞掉未知字段。
- mock 只在显式 mocking mode 启用；生产/dev real 模式不得被 MSW 截获。
- endpoint 移除时同步删除 adapter、store、route、view 和测试。

## 3. 登录与会话

- 管理员 SPA 是静态登记的 first-party public OIDC client。
- 使用 Authorization Code + PKCE S256、state、nonce 和精确 redirect URI。
- access token 只保存在内存；禁止 localStorage/sessionStorage/indexedDB 持久保存 bearer/refresh token。
- 页面刷新后的长期会话首版依赖 OP 登录 session 重新授权；若产品要求无跳转刷新，再设计 BFF/httpOnly session，不在 SPA 直接持久化 refresh token。
- logout 调用 RP-Initiated Logout，清除本地内存状态并验证 post logout redirect。
- 401 触发受控重新认证，403 呈现权限不足，不能用无限重试循环。

## 4. 权限与导航

- 后端永远执行真实授权；前端 capability set 只控制菜单、按钮和提示。
- 路由与导航是产品显式清单，不根据后端目录或数据库动态生成代码页面。
- 可按 `/auth/me` 和明确的 capability/readmodel 响应隐藏未启用功能。
- 深链接无权限时显示稳定错误页，不只依赖导航隐藏。

## 5. 初始业务页面目标

按后端能力逐步接入：

- 用户、角色和权限。
- OIDC clients、grants/sessions、key rotation 状态（私钥不可见）。
- post/page 内容、定时发布、置顶和引用。
- category/tag terms 与 assignments；page 不显示 taxonomy 控件。
- SEO settings 与外部 assets 引用。
- notification delivery、workflow/task failure 和显式恢复操作。
- points accounts/ledger/admin adjustment。
- payment orders/webhook receipts/refunds。
- capability diagnostics 和 readmodel summaries。

当前 dashboard 壳和 interaction 绑定删除。新的概览只消费后端 `AdminSummaryProvider` 聚合 DTO，不并行调用多个 service 后在前端猜测状态。

## 6. 内容与 SEO 表单

- content type metadata 由显式后端契约提供，用于选择 data schema 对应的受控表单组件；不执行服务端下发代码。
- post 显示 category/tag 控件，page 不显示。
- schedule 使用用户选择时区输入，提交前转换为带 offset 时间并由后端保存 UTC。
- 置顶编辑 `is_pinned`/`pin_rank`，列表按后端返回顺序显示，不在前端二次置顶。
- SEO 设置页只编辑站点级默认值；前台站点负责单页 meta/路由实现。

## 7. 敏感操作

- 封禁、删除、角色替换、OIDC client secret、key rotation、积分调整、退款、任务重试和修复 Command 要求二次确认及 reason（后端要求时）。
- secret 只在创建时一次展示，不写日志/store/persistence。
- 表单错误展示安全 message 和 request ID，开发控制台也不得打印 token/provider payload。
- 禁止在浏览器中实现支付 webhook 验签或决定 captured 状态。

## 8. 生产构建与部署

- `npm run build` 产生静态资源；生产不得运行 `vite` dev server 或 `vite preview`。
- 静态资源由 Caddy、Nginx、对象存储/CDN 或经批准的静态服务器发布。
- 若 admin 与 API 分离 origin，部署配置必须固定 API/issuer URL、CORS allowlist、OIDC redirect/post-logout URI 和 CSP。
- sourcemap 发布、缓存策略、安全 header、SPA fallback 和 immutable hashed assets 必须由生产容器/托管平台明确配置。
- Vite proxy 仅用于开发 profile。

## 9. 质量门

- `npm ci` 使用已提交 `package-lock.json`，不以 `--force` 绕过 peer conflict。
- format/lint/check、typecheck、unit、production build 全绿。
- OpenAPI check 和生成类型无漂移。
- Playwright 使用真实后端覆盖 OIDC 登录、权限、内容、积分/支付管理的已实现核心路径。
- 生产 bundle 不包含 mock worker、测试 secret 或开发 API endpoint。
