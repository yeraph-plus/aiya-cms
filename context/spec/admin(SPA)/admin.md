# 管理员端规格

## 1. 定位

`admin/` 是独立 Vue SPA，只通过 HTTP/OpenAPI 使用系统能力。它不是后端插件宿主，不读取 Python 源码、数据库、migration manifest 或 capability 内部注册表。

保留 Sakai Vue 的 MIT 许可证 `admin/LICENSE.md` 和来源说明 `admin/UPSTREAM.md`；重构业务页面不得移除归属信息。

管理员端显示名称固定为大写 `AIYA-CMS`（`admin/src/env.ts` 的 `APP_NAME`），不随站点或品牌资源动态变化。

界面基座为 Sakai Vue UI kit（MIT），组件与页面清单见 `admin-uikit.md`。

## 2. 契约

- 所有 API 类型从根 OpenAPI snapshot 生成。
- API adapter 引用生成的 paths/operations/components，不维护平行 TypeScript DTO。
- 不允许 `any`/`unknown` payload、手工复制 Page/Error/业务 schema 或静默吞掉未知字段。
- mock 只在显式 mocking mode 启用；生产/dev real 模式不得被 MSW 截获。
- endpoint 移除时同步删除 adapter、store、route、view 和测试。
- 管理员 SPA 的业务 adapter 只能调用 `/api/v1/admin/**`；共同认证面仅允许 `/api/v1/auth/**`、带 `auth` tag 的 `/api/v1/me` 投影和 issuer 下的 OIDC 协议端点。禁止为了复用用户侧页面而调用 content、points、membership、payment 等普通用户业务端点。
- `/api/v1/admin/**` 表示管理传输边界，不改变 capability 所有权；router 仍只调用公开 Command/Query，禁止把 ORM/Repository 暴露为通用 CRUD。

## 3. 登录与会话

- 管理员 SPA 是静态登记的 first-party public OIDC client（`client_id=admin`，issuer/client/redirect URI 由发布配置注入并精确匹配）。
- 发布配置使用单一 `AIYA_ISSUER` 注入值；Vite 将其暴露给 SPA，禁止再维护 `VITE_OIDC_ISSUER` 平行变量。backend、Discovery 和 SPA 的 issuer 必须完全一致。
- 使用 `oidc-client-ts`（Apache-2.0）实现 Authorization Code + PKCE S256、Discovery、state/nonce 校验与 RP-Initiated Logout；协议细节不手写。
- Login 页保留网页表单登录：以 `application/x-www-form-urlencoded` + `Accept: application/json` `POST {issuer}/oidc/login`（携带用户名密码与 authorize 参数），凭据校验由后端 OP 完成，SPA 不直接校验密码；成功返回前端 callback URI，协议错误由 SPA 跳转 `/auth/error`，不把错误 JSON 导航到 OP 页面。
- 回调路径固定为 `{origin}/callback` 与 `{origin}/logged-out`，与后端 install 注册的 client redirect/post-logout URI 一致。
- access token 只保存在内存（`InMemoryWebStorage` 包装的 userStore）；state/nonce/code verifier 等一次性协议材料只放 sessionStorage；禁止 localStorage/sessionStorage/indexedDB 持久保存 bearer/refresh token；不请求 `offline_access`，关闭 silent renew。
- 页面刷新后的长期会话首版依赖 OP 登录 session 重新授权；若产品要求无跳转刷新，再设计 BFF/httpOnly session，不在 SPA 直接持久化 refresh token。
- OP 登录 session cookie 为 HttpOnly/SameSite=Lax，要求 SPA 与 OP 同 site 部署（同域或子域）；跨 site 部署需先设计 BFF 或 cookie 策略，否则表单登录不可用。
- logout 调用 RP-Initiated Logout，清除本地内存状态并验证 post logout redirect。
- 401 触发单飞受控重新认证（共享 Promise、不并发），403 呈现权限不足，不能用无限重试循环。
- 除登录外，公共认证壳必须提供注册、邮箱验证、密码重置请求和密码重置确认表单，分别调用 `/api/v1/auth/register`、`/verify-email`、`/password-reset/request`、`/password-reset/confirm`。
- 注册成功只提示检查邮箱，不显示 challenge token；密码重置请求对任何标识显示相同成功状态，不泄露用户是否存在。
- 公共认证路由固定为 `/auth/login`、`/auth/register`、`/auth/verify-email`、`/auth/password-reset`、`/auth/password-reset/confirm`、`/callback` 和 `/logged-out`。

## 4. 权限与导航

- 后端永远执行真实授权；前端 capability set 只控制菜单、按钮和提示。
- 路由与导航是产品显式清单，不根据后端目录或数据库动态生成代码页面。
- 可按 `/me` 和明确的 capability/readmodel 响应隐藏未启用功能。
- 深链接无权限时显示稳定错误页，不只依赖导航隐藏。

### 4.1 产品路由与菜单

生产主路由是工作台，不把记录详情注册成“详情页 + 返回列表”子路由：

| 分组 | 路由 | 页面职责 |
| --- | --- | --- |
| 首页 | `/dashboard` | 管理汇总、趋势和近期失败 |
| 内容 | `/content/write` | 新文章工作台 |
| 内容 | `/content/articles` | 文章列表、抽屉内查看/编辑 |
| 内容 | `/content/taxonomies` | 分类维度和 term 管理 |
| 内容 | `/content/comments` | 评论查询、详情抽屉和审核操作 |
| 用户 | `/users` | 用户列表和单用户工作台抽屉 |
| 用户 | `/users/permissions` | 角色、权限矩阵和主体授权 |
| 用户 | `/users/points` | 积分账户、账本和命名管理操作 |
| 用户 | `/users/membership` | 等级只读目录和订阅管理 |
| 用户 | `/users/payments` | 订单、回执和退款；读合同完成后注册 |
| 系统 | `/system/audit` | 审计查询和详情抽屉 |
| 系统 | `/system/operations` | outbox/inbox/task 安全摘要和恢复操作 |
| 系统 | `/system/assets` | 稳定资源引用、上传和外部对象登记 |
| 系统 | `/system/notifications` | delivery/attempt 与恢复；合同完成后注册 |
| 系统 | `/system/oidc` | client/grant/session/key 管理；合同完成后注册 |
| 设置 | `/settings` | 同页管理所有已注册 setting group |

菜单顺序固定为 Dashboard、Content、Users、System、Settings。路由未完成后端契约时不得注册、不得进入菜单，也不得指向 placeholder。

### 4.2 叠加层规则

- 列表记录的查看、编辑和单记录操作使用右侧 Drawer；创建小型资源、二次输入和确认使用 Dialog。
- “写文章”是独立工作台；文章列表中的编辑复用同一 `ArticleForm` 内核，但由 Drawer 承载，不注册 `/content/:id`。
- 用户列表只打开一个 `UserWorkspaceDrawer`，内部按权限提供 profile、roles、points、membership、payments 等 tab；不叠加多个同级 Drawer。
- 设置组在 `/settings` 同页展示和编辑，不注册 `/settings/:groupKey`。
- 可分享的叠加层状态可以使用经过 allowlist 校验的 query；query 不得携带 secret、token、signed URL 或敏感 provider payload。

### 4.3 通用页面壳

- `PageShell` 统一标题、副标题、间距、权限态、主操作和组合刷新按钮；页面不得各自拼装标题 Toolbar。
- `SurfaceCard` 统一区块标题、说明、actions、边框和 loading/empty/error 容器。
- `EntityDrawerShell`、`FormDialogShell` 和 `SensitiveActionDialog` 统一叠加层宽度、footer、未保存变更保护、reason 和危险操作确认。
- 列表继续使用服务端分页 `PagedTable`；状态反馈继续使用 `PageState`/`ApiErrorMessage`，后端 message 与 request ID 不得被隐藏。

## 5. 初始业务页面目标

按后端能力逐步接入：

- 用户、角色和权限。
- OIDC clients、grants/sessions、key rotation 状态（私钥不可见）。
- 一个内容列表中的 post/page 内容、定时发布、置顶和引用。
- category/tag terms 与 assignments；page 不显示 taxonomy 控件。
- system/assets 中的稳定 asset references、上传 intent 和外部对象登记；bucket 不归属于 content。
- Settings 页面中的 SEO settings 与外部 assets 引用。
- notification delivery、workflow/task failure 和显式恢复操作。
- points accounts/ledger/admin adjustment。
- payment orders/webhook receipts/refunds。
- capability diagnostics 和 readmodel summaries。
- settings group/SEO 编辑、audit 和 execution entries 分页查询；settings 字段控件由后端 Field metadata 驱动，不按具体配置 slug 硬编码。

当前 dashboard 壳和 interaction 绑定删除。新的概览只消费后端 `AdminSummaryProvider` 聚合 DTO，不并行调用多个 service 后在前端猜测状态。

### 5.1 后端预留定义与管理端边界

下列定义属于后端注册/发布合同，不因存在数据库表或内部 Command 就自动成为管理员 API：

| 定义 | 当前 HTTP 导出 | 管理端约束 |
| --- | --- | --- |
| points program | 未导出 program 目录或管理接口；现有 ledger/adjust 只接受已注册 `program_key` | 不创建 program CRUD 页面、路由或占位按钮 |
| membership level | 仅 `GET /api/v1/admin/membership/levels` 只读目录 | 可展示等级，不提供创建、编辑、删除或状态修改 |
| notification template | 未导出模板读取或管理接口 | 通知页面只处理 delivery/attempt 和显式恢复操作，不提供模板编辑器 |

这些接口缺席是有意的后端预留边界，不是要求前端用 mock、settings 字段或通用 CRUD 补齐的合同缺口。未来开放时仍须先完成 capability 规格、权限/审计、失败测试、RouterSpec、OpenAPI 和生成类型闭环。

## 6. 国际化

- 管理端使用 Vue I18n Composition API，支持 `zh-CN` 与 `en-US`；路由使用稳定 `titleKey`，菜单使用稳定 `labelKey`，页面和共享组件不得硬编码混合语言产品文案。
- locale 选择顺序为已保存的 UI 偏好、浏览器支持语言、`zh-CN` 默认值；只允许持久化 locale，不持久化 bearer/refresh token。
- 顶栏提供语言切换；页面标题、菜单、按钮、表单说明、空状态、状态枚举和前端验证文案随 locale 更新。
- 后端保持纯英文：普通 API `message` 原样展示，并同时展示 `request_id`；前端不得按后端 error code/message 建立翻译字典。日志、审计 action、capability key、operation key 和 OpenAPI 字段名不翻译。
- 日期、数字和金额使用当前 locale 格式化，但提交给后端的 datetime、enum、minor-unit amount 和稳定 key 不因语言变化。
- 两套词典的 key 必须完全一致；缺 key、fallback 泄漏或路由/menu 使用裸显示字符串均由单元测试阻止。

## 7. 内容与 SEO 表单

- content type metadata 由显式后端契约提供，用于选择 data schema 对应的受控表单组件；不执行服务端下发代码。
- post 显示 category/tag 控件，page 不显示。
- 内容列表默认展示所有已注册内容类型，type filter 只改变同一列表的查询条件，不创建 posts/pages 两套页面。
- schedule 使用用户选择时区输入，提交前转换为带 offset 时间并由后端保存 UTC。
- 置顶编辑 `is_pinned`/`pin_rank`，列表按后端返回顺序显示，不在前端二次置顶。
- Settings 页面中的 SEO group 只编辑站点级默认值；前台站点负责单页 meta/路由实现。

## 8. 敏感操作

- 封禁、删除、角色替换、OIDC client secret、key rotation、积分调整、退款、任务重试和修复 Command 要求二次确认及 reason（后端要求时）。
- secret 只在创建时一次展示，不写日志/store/persistence。
- 表单错误展示安全 message 和 request ID，开发控制台也不得打印 token/provider payload。
- 禁止在浏览器中实现支付 webhook 验签或决定 captured 状态。

## 9. 生产构建与部署

- `npm run build` 产生静态资源；生产不得运行 `vite` dev server 或 `vite preview`。
- 静态资源由 Caddy、Nginx、对象存储/CDN 或经批准的静态服务器发布。
- 若 admin 与 API 分离 origin，部署配置必须固定 API/issuer URL、CORS allowlist、OIDC redirect/post-logout URI 和 CSP。
- sourcemap 发布、缓存策略、安全 header、SPA fallback 和 immutable hashed assets 必须由生产容器/托管平台明确配置。
- Vite proxy 仅用于开发 profile。

## 10. 质量门

- `npm ci` 使用已提交 `package-lock.json`，不以 `--force` 绕过 peer conflict。
- format/lint/check、typecheck、unit、production build 全绿。
- OpenAPI check 和生成类型无漂移。
- 路由、菜单和 `zh-CN`/`en-US` 词典 key parity 测试通过；生产页面不存在面向用户的裸硬编码文案。
- Playwright 使用真实后端覆盖 OIDC 登录、权限、内容、积分/支付管理的已实现核心路径。
- 生产 bundle 不包含 mock worker、测试 secret 或开发 API endpoint。
