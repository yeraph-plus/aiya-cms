# 管理员 SPA 从壳到生产上线计划

状态：规划基线。本文替换此前只描述 TS 骨架和占位路由的旧记录；它是一次性施工计划，不替代 `context/` 规格事实源。实际行为仍以 `context/admin dash spec (SPA)/admin.md`、`context/admin dash spec (SPA)/admin-uikit.md`、`context/spec/http-openapi.md` 和当前 `openapi.json` 为准。

## 0. 施工状态

| 批次 | 状态 | 完成记录 |
| --- | --- | --- |
| P0 合同和基线冻结 | ✅ 2026-08-10 | OpenAPI 端点/权限/页面归属清单：`context/admin-openapi-inventory.md`；P0 四门失败测试已落为 `src/tests/unit/`（router-meta、menu-visibility、type-drift、demo-exclusion）并通过 |
| P1 Sakai kit TS parity 和生产壳 | ✅ 2026-08-10 | `src/router/` 拆分（meta/public/app）、`src/navigation/`（menu/visibility）接入 AppMenu；共享组件 `src/components/feedback|data`（PageState、ApiErrorMessage、ConfirmAction、PageToolbar、PagedTable、EmptyTable）与 `src/composables/`（useAsyncState、useCapability）；auth 页去除演示图与假表单（Login/AccessDenied/Error/Callback）；`Placeholder.vue`、`/pages/empty` 删除；显示名固定 `AIYA-CMS`（`src/env.ts`）；`src/demo/` 保持只读样式参考 |
| P2 类型化 API 和 OIDC session | ✅ 2026-08-10 | 采用 `oidc-client-ts` 3.5（见 §13 决策门）：`src/auth/`（oidc.ts/storage.ts/session.ts 状态机/unauthorized.ts 401 单飞）、`src/api/`（client.ts X-Request-ID/Idempotency-Key、auth.ts me adapter、index.ts 延迟装配由 main.ts 组合根 configureApi）、`src/env.ts` OIDC 配置校验；Login 页保留表单登录（POST `{issuer}/oidc/login`），Callback 页完成 code 交换，回调路径 `/callback`、`/logged-out` 与后端 client 注册精确匹配；单测 42 项通过。真实 provider E2E 待后端容器环境就绪后补齐 |
| P3 路由、守卫和导航 | ✅ 2026-08-10 | `src/router/`（public/app-routes、meta）与 `src/navigation/`（menu/visibility）落地；守卫按 §6.3 实现：session 初始化（error 状态下次导航重试）、登录态访问 login/callback 均重定向 dashboard、capability deny → `/auth/access-denied`、404 兜底、标题写入；blocked 路由不注册；深链回跳经 OP 往返由 `auth/storage.ts` 一次性 redirect 材料（sessionStorage，同源校验）承接，Callback 完成 code 交换后取回；新增 router-guard（10 项：匿名重定向+redirect query、safe redirect、capability deny、登录态访问 login/callback、刷新深链、404、blocked 不注册、初始化失败重试）与 redirect-storage（4 项）单测；业务路由随 P4–P7 页面批次注册，未注册菜单项由 visibility.ts 按 capability + 路由注册双条件隐藏 |
| P5 Content、Taxonomy 和 Assets | 🚧 2026-08-11 | 单一 `/content` 全类型列表、基础编辑器、生命周期/引用、post taxonomy assignment 读取与保存、flat taxonomy 管理、`/system/assets` 稳定引用管理和上传 workflow 页面已接入；公开用户侧 content feature 契约不在本批次；真实后端浏览器 E2E 待发布门补齐 |
| P4+ | ⬜ | 业务路由注册（§7.2，随页面批次落地）、页面批次 P4–P7、清理与上线 P8 |

施工约定：业务页面目录（`src/pages/{identity,content,system,operations}`）与 domain adapter（`src/api/*.ts`）按 §4 已占位，随批次落地；未注册路由的菜单项由 `visibility.ts` 按 capability + 路由注册双条件隐藏，父组无可见子项时整体隐藏；blocked 路由（§7.3）不注册、不占位。

## 1. 目标与边界

### 1.1 目标

- 将 `admin/` 从 Sakai Vue 的 UI 空壳建设为可上线的 aiya-cms 管理 SPA。
- 保留 Sakai Vue 的布局、主题、MIT 许可证和来源说明；业务页面全部重写为 TypeScript Vue 代码。
- 以 `openapi.json` 为唯一 HTTP 类型入口，生成 `src/api/schema.d.ts`，不手写平行后端 DTO。
- 从头确定生产路由、路由守卫、菜单组、权限显示规则和页面使用的 PrimeVue kit 组件。
- 按真实后端能力逐页交付；当前 OpenAPI 没有覆盖的旧页面先补后端合同，不用占位页、mock 或前端猜测填充。
- 上线代码和生产 bundle 不保留当前 dev 分支的 demo 画廊、mock 数据、开发认证绕过和开发路由。

### 1.2 非目标

- 不把 `src/demo/` 的静态服务改造成业务 API adapter。
- 不在前端实现后端授权、支付 webhook 验签、captured 状态判断或 refresh token 持久化。
- 不从数据库、后端目录或 capability 列表动态生成页面和路由。
- 不把所有 PrimeVue 组件重新封装成平行组件库；只有出现重复业务交互时才增加薄封装。

## 2. 当前基线审计

### 2.1 可以保留的基座

| 范围 | 当前文件 | 处理 |
| --- | --- | --- |
| Vue/TypeScript/Vite | `admin/src/main.ts`、`admin/vite.config.ts`、`admin/tsconfig*.json` | 保留并补生产配置、测试命令和环境校验 |
| Sakai 布局 | `admin/src/layout/` | 作为生产壳保留；业务菜单改为显式产品清单 |
| 主题 | `layout/composables/layout.ts`、`AppConfigurator.vue` | 保留 `useLayout()` 为唯一主题/布局状态入口 |
| 生成类型 | `admin/src/api/schema.d.ts` | 只由 `npm run generate:api` 生成，禁止手改 |
| 认证壳 | `admin/src/pages/auth/`、`FloatingConfigurator.vue` | 保留视觉基座，删除假登录行为，接入 OIDC Code + PKCE |
| 许可证和来源 | `admin/LICENSE.md`、`admin/UPSTREAM.md` | 发布时必须保留 |

### 2.2 当前必须重写的部分

| 范围 | 当前问题 | 目标 |
| --- | --- | --- |
| `src/router/index.ts` | 仍是壳页和旧业务名，只有同步 token 判断，包含 dev auth bypass | 改成异步 session 初始化、OIDC callback、能力守卫和生产路由表 |
| `src/auth/session.ts` | 只有内存 token/me，未实现授权码、过期、401 单飞和登出 | 实现完整会话生命周期；任何 bearer token 只存在内存 |
| `src/api/client.ts` | `body`、错误体和请求参数仍有 `unknown`/宽泛字符串入口，未覆盖 query/header/idempotency | 以生成的 `paths`/`components` 建立类型化 domain adapter |
| `src/pages/Dashboard.vue` | 只显示 `Shell ready`，没有汇总契约 | 只有后端提供 `AdminSummaryProvider` DTO 后才能实现生产概览 |
| `src/layout/AppMenu.vue` | 仍包含 `Demo Gallery` 和旧的 Notifications/Payments 等入口 | 使用显式菜单清单，并按 `/me` capability 过滤 |
| `src/demo/` | 是 kit 画廊和 Sakai 交互参考，不是业务实现 | 开发阶段只读参考；P8 验收后整体删除 |
| `public/demo/`、构建产物 | 含演示图片和静态 mock 数据 | 逐项确认无生产引用后删除或移出发布上下文 |

### 2.3 已确认过时的记录

- 旧计划中“P0/P0.5 已完成”的状态不作为后续完成依据，必须以本计划的验收门重新确认。
- 旧路由 `/identity/oidc-clients`、`/operations/notifications`、`/operations/payments`、`/system/diagnostics` 的页面目标不能直接视为当前可实现合同。
- 当前 `openapi.json` 有 OIDC 协议端点，但没有管理员 OIDC client/grant/session/key rotation 管理端点；两者不能混为一个页面能力。
- 当前 OpenAPI 只有支付退款 command，没有支付订单列表/详情；只有积分调整 command，没有管理员积分账户/流水列表；不能先做看似完整的 DataTable。
- 当前 `openapi.json` 没有管理员汇总 DTO，也没有 content type schema metadata；Dashboard 和动态内容表单在合同补齐前不得宣称完成。
- `src/demo/pages/Crud.vue` 只提供 DataTable、Toolbar、Dialog、确认操作的交互样式参考；其中的 Product DTO、静态 service 和本地删除逻辑全部不能进入业务页。

## 3. 事实来源与开发规则

每个页面或 API adapter 按以下顺序施工：

1. 更新对应的 `context/spec/` 合同，明确路由、权限、DTO、错误、分页和副作用。
2. 在后端或管理员端先写证明旧行为不满足的失败测试。
3. 更新后端实现、`openapi.json`、`openapi.sha256` 和生成的 `src/api/schema.d.ts`。
4. 编写类型化 API adapter 和 adapter 单元测试。
5. 编写页面、表单、加载/错误/空状态和权限显示。
6. 用真实后端完成 Playwright 核心路径和负向路径。
7. 通过前端 typecheck、lint、production build 后才能进入下一页。

以下规则在每个阶段都适用：

- API 类型只能来自 `src/api/schema.d.ts` 的 `paths` 和 `components`。
- 不手写 `Page`、`Error`、Subject、Content、Role 等后端业务 DTO。
- 生产业务 payload 不使用 `any`/`unknown` 逃避类型；JSONB 字段必须有明确的表单 schema 或受控 JSON 编辑器。
- GET/HEAD 页面不得因为加载、计数、缓存刷新而写库或发业务 command。
- 列表查询的 `page` 从 1 开始，分页状态、过滤器和排序写入 URL query，可复制深链接。
- 写操作统一经过 domain adapter；成功后以服务端返回 DTO 更新页面，不在前端猜测状态。
- 401 只触发一次受控重新认证；403 显示权限不足；不得无限重试。
- 敏感操作必须二次确认，按接口合同提交 `reason`、`idempotency_key` 或版本字段。
- token、provider payload、secret、一次性 client secret 不写日志、store、URL 或浏览器持久存储。
- mock 只有显式 mocking mode 可用；真实 dev profile 不得被 MSW 或静态 service 截获。

## 4. 目标前端目录

业务页不再按 Sakai 的 `views` 目录组织，而是按产品域分组；kit 壳、HTTP 适配、认证和导航保持独立。

```text
admin/
  public/
    favicon.ico
  src/
    main.ts                         # 组合根：环境、router、PrimeVue、全局服务
    App.vue                         # 根 router-view，不承载业务规则
    env.ts                          # API/issuer/client/redirect 配置校验
    api/
      schema.d.ts                   # openapi-typescript 生成，禁止手改
      client.ts                     # fetch、Authorization、request ID、204、401
      errors.ts                     # ApiError、安全错误 message 和 request ID 映射
      pagination.ts                  # 生成 Page DTO 的分页读取辅助
      index.ts                      # 只导出公开 domain adapter
      auth.ts                       # /me 与 OIDC 辅助 HTTP 操作
      identity.ts                   # users、roles、capabilities
      content.ts                    # content lifecycle、references、content types
      taxonomy.ts                   # dimensions、terms、assignments
      assets.ts                     # upload intent、finalize、metadata、signed URL
      settings.ts                   # setting groups、SEO、reset、version
      audit.ts                      # audit query filters
      operations.ts                 # points adjustment、payments refund
      system.ts                     # readiness、capability diagnostics、summary
    auth/
      session.ts                    # 内存 access token、MeDTO、状态机
      oidc.ts                       # Discovery、PKCE、state、nonce、token/logout
      storage.ts                    # 只存短时 state/code_verifier/nonce，不存 bearer
      unauthorized.ts                # 401 单飞、清 session、重新认证
    router/
      index.ts                      # createRouter、显式 route records、guard
      meta.ts                       # RouteMeta 类型和 capability 元数据
      public-routes.ts              # login、callback、access denied、error、404
      app-routes.ts                 # 生产业务路由清单
    navigation/
      menu.ts                       # 产品显式菜单组，不从 API 生成路由
      visibility.ts                 # capability 过滤和递归隐藏空分组
    layout/
      AppLayout.vue
      AppTopbar.vue
      AppSidebar.vue
      AppMenu.vue
      AppMenuItem.vue
      AppFooter.vue
      AppConfigurator.vue
      composables/layout.ts
    components/
      feedback/                     # PageState、ApiErrorMessage、ConfirmAction
      data/                         # PageToolbar、PagedTable、EmptyTable
      forms/                        # FormField、DirtyGuard、JsonEditor
      content/                      # ContentStatus、ContentActions、ReferencePanel
      assets/                       # AssetPicker、UploadIntentFlow
    composables/
      useAsyncState.ts              # loading/error/success 生命周期
      usePagedQuery.ts              # URL query + Page DTO
      useUnsavedChanges.ts          # 编辑页离开确认
      useCapability.ts              # 页面动作可见性，不承担后端授权
    pages/
      auth/
        Login.vue
        Callback.vue
        AccessDenied.vue
        Error.vue
      dashboard/
        Dashboard.vue
      identity/
        UsersList.vue
        UserDetail.vue
        Roles.vue
        Capabilities.vue
      content/
        ContentList.vue
        ContentEditor.vue
        Taxonomy.vue
      system/
        SettingsGroups.vue
        SettingGroupEditor.vue
        SeoSettings.vue
        AuditLog.vue
        Diagnostics.vue
      operations/
        PointsAdjustment.vue
        Payments.vue            # 仅在订单读 API 合同完成后加入
      NotFound.vue
    tests/
      unit/
      components/
      e2e/
    demo/                          # 仅迁移验收期存在；P8 删除
  LICENSE.md
  UPSTREAM.md
```

目录约束：

- `pages` 只组合 adapter、composable 和 kit 组件，不直接调用 `fetch`。
- `components` 只放跨两个以上业务页复用且不包含领域规则的 UI 交互。
- `api` 不导出 ORM 语义，不保存全局业务缓存，不隐藏写操作。
- 不引入 Pinia 作为默认全局状态层；session 和 layout 是已有的两个全局状态边界，列表/编辑状态默认归页面所有。
- 如果后续确实需要跨页 readmodel cache，先写缓存失效和读副作用合同，再增加独立模块。

## 5. OpenAPI 适配层

### 5.1 客户端职责

`src/api/client.ts` 重写为以下职责：

- 从 `env.ts` 读取固定 API origin/base path，开发 proxy 只存在 dev profile。
- 自动附加内存中的 Bearer token、`X-Request-ID`，按需要附加 `Idempotency-Key`。
- 将成功响应区分为 DTO、Page DTO、array 和 204 void。
- 将普通错误统一为 `ApiError { status, code, message, details, requestId }`；只把安全 message 交给页面。
- 401 调用 `unauthorized.ts` 的单飞回调；当前请求失败，不自动无限重放。
- 不把完整 response payload、token、provider 错误或 secret 打进 console。
- 支持 AbortSignal；离开页面或 query 变更时取消旧请求。

### 5.2 Domain adapter

每个 adapter 函数固定绑定一个 operationId，并从生成类型推导参数和返回值。建议命名如下：

| 文件 | 主要 operationId/范围 |
| --- | --- |
| `auth.ts` | `me_api_v1_auth_me_get`，OIDC Discovery/authorize/token/logout 由 `oidc.ts` 按协议处理 |
| `identity.ts` | `list_users`、`get_user`、`ban_user`、`unban_user`、`delete_user` |
| `identity.ts` | `list_roles`、`create_role`、`assign_role`、`revoke_role`、`list_capabilities` |
| `content.ts` | content list/get/create/update、submit/reject/schedule/unschedule/publish/archive/restore/pin/purge、references |
| `taxonomy.ts` | dimensions、terms、create/update/archive、target assign/remove |
| `assets.ts` | create intent、外部 upload、finalize、register/get/update/delete、resolve URL |
| `settings.ts` | list/get/update/reset setting groups |
| `audit.ts` | paged audit entries and all declared filters |
| `operations.ts` | `adjust_points`、`request_refund`，后续追加真实订单/账本读操作 |
| `system.ts` | `/healthz`、`/api/v1/health`、`admin/capabilities`、summary contract |

### 5.3 页面与 OpenAPI 的同步门

- 每次后端 operationId、schema、error response、security、tag 或分页字段变化，必须同一提交重新生成 `schema.d.ts` 并运行 typecheck。
- 删除 endpoint 时同时删除 adapter、页面调用、route、menu item 和测试。
- `openapi.sha256` 不匹配时禁止合并管理员页面变更。
- 生成类型不能通过 `as any`、`as unknown as` 或平行 interface 绕过。
- 只允许在 adapter 内做路径和 query 参数映射；页面不拼接 API URL。

## 6. 认证、会话与路由守卫

### 6.1 OIDC 会话方案

管理员 SPA 使用 first-party public OIDC client，协议实现采用 `oidc-client-ts`（决策门见 §13）：

- Authorization Code + PKCE S256；issuer、client id、redirect URI、post logout URI 从发布配置注入并做精确匹配（`src/env.ts`）。
- Login 页保留网页表单登录：表单 `POST {issuer}/oidc/login` 携带用户名密码与 `OidcClient.createSigninRequest` 生成的 authorize 参数；凭据校验在后端 OP，SPA 不直接校验密码。
- 回调路由固定为 `/callback`（signin callback）与 `/logged-out`（post logout redirect），与后端 install 注册 client（`client_id=admin`）的 redirect/post-logout URI 精确一致。
- access token 只存 `session.ts` 内存（userStore 为 `InMemoryWebStorage` 包装）；sessionStorage 只保存 state/nonce/code verifier 等非 bearer 的一次性协议材料；不请求 `offline_access`，`automaticSilentRenew` 关闭。
- 刷新页面时不恢复 bearer；按规格重新走 OP session 授权（OP session cookie 仍在则 302 直达 code）。若以后要无跳转刷新，单独设计 BFF/httpOnly session，不把 refresh token 加入 SPA。
- logout 先清除本地内存状态，再执行 RP-Initiated Logout（`signoutRedirect`），post logout redirect 指向 `/logged-out`。
- 401 由 `unauthorized.ts` 单飞处理（共享 Promise 防止并发重认证），置 session 为 expired 并跳转 login。

### 6.2 路由元数据

路由元数据固定为：

```ts
interface RouteMeta {
  title: string;
  requiresAuth: boolean;
  requiredCapability?: string;
  shell: 'auth' | 'app';
}
```

页面内按钮、tab 和行操作另用显式 action capability，不把所有操作权限塞进 route meta。`requiredCapability` 只控制可见性和早期导航体验，后端仍是最终授权边界。

### 6.3 `beforeEach` 规则

1. 等待 `session.initialize()` 完成；初始化期间不让受保护页面短暂渲染。
2. `requiresAuth` 且无有效 session 时，跳转 `/auth/login`，通过受控 query 保存同源 `redirect`。
3. 已登录访问 `/auth/login` 或 `/auth/callback` 的完成态时，跳转 dashboard 或原始 redirect。
4. 已登录但缺少 `requiredCapability` 时，跳转 `/auth/access-denied`，保留安全的目标路由名称，不把敏感 query 原样回显。
5. 401 进入重新认证流程；正在重新认证时复用同一个 Promise，禁止循环跳转。
6. 403 由 adapter/页面显示权限不足和 request ID，不伪装成 404。
7. 写入 `document.title` 和页面级 loading/error 状态；未知路径进入生产 404。
8. `VITE_DEV_AUTH` 等本地豁免只允许开发构建读取，P8 前必须删除代码和配置，不得进入生产 bundle。

## 7. 生产路由清单

以下是按当前 OpenAPI 重新规划的生产路由。所有路由都显式写入 `app-routes.ts`；不存在“根据 capability 或后端目录自动发现页面”。

### 7.1 公共路由

| 路由 | 页面 | 守卫 | 说明 |
| --- | --- | --- | --- |
| `/auth/login` | Login | `requiresAuth: false` | 保留网页表单登录；表单 POST 到 OP `/oidc/login`（用户名/密码由后端 OP 校验，SPA 不直接校验管理员密码） |
| `/callback` | Callback | `requiresAuth: false` | OIDC 授权回调（与后端 client 注册的 `{origin}/callback` 精确匹配），成功后进入原始目标 |
| `/logged-out` | 重定向到 login | `requiresAuth: false` | RP-Initiated Logout 的 post logout redirect 落点 |
| `/auth/access-denied` | AccessDenied | `requiresAuth: false` | 403 或前端能力缺失的稳定错误页 |
| `/auth/error` | Error | `requiresAuth: false` | OIDC/API 非安全错误摘要和 request ID |
| `/:pathMatch(.*)*` | NotFound | `requiresAuth: false` | 不保留 Sakai demo 的 `/pages/empty`、`/pages/notfound` 路由 |

### 7.2 当前 OpenAPI 可直接进入开发的业务路由

下表的 `/admin/...` 为可读性省略写法，实际前缀均为 `/api/v1/admin/...`。

| 路由 | 页面职责 | 直接使用的 API | 页面 capability |
| --- | --- | --- | --- |
| `/identity/users` | 用户分页、状态过滤、详情入口 | `GET /admin/users` | `identity.users.read` |
| `/identity/users/:userId` | 用户详情、ban/unban/delete | `GET /admin/users/{id}`、ban、unban、delete | read 页面；动作分别为 `identity.users.ban/unban/delete` |
| `/identity/roles` | 角色列表、创建角色、按 subject 分配/撤销 | `/admin/roles`、assign、revoke | read/create `access.roles.read/manage`；assign `access.roles.assign` |
| `/identity/capabilities` | 权限 key 只读目录 | `GET /admin/capabilities` | `access.roles.read` |
| `/content` | 一个页面展示所有已注册内容类型，可按 type/status 过滤 | `GET /admin/content` | `content.read` |
| `/content/new` | 创建内容并选择当前已注册类型 | `POST /admin/content` | `content.write` |
| `/content/:contentId` | 编辑内容、状态流转、引用、taxonomy | content get/patch、workflow、references、taxonomy assignment | read；动作按 content action capability |
| `/content/taxonomy` | dimension/term 管理 | `/admin/taxonomy/...` | `taxonomy.read/manage` |
| `/system/assets` | 稳定 asset reference 列表、上传和外部对象登记 | `/admin/assets/...` | `assets.read`；动作按 assets capability |
| `/system/settings` | setting group 列表 | `GET /admin/settings/groups` | `settings.read` |
| `/system/settings/:groupKey` | 受控 setting group 编辑和 reset | get/update/reset group | read；写操作由 group-specific backend permission 决定 |
| `/system/seo` | 固定 SEO group 编辑入口 | setting group API，group key 固定为 `seo` | `settings.read`；写操作使用 `settings.seo.update` |
| `/system/audit` | 审计分页、动作/actor/outcome/时间过滤、详情抽屉 | `GET /admin/audit/entries` | `audit.read` |
| `/system/diagnostics` | readiness、已注册 capability、可用性摘要 | `/api/v1/health`、`/admin/capabilities` | 页面至少需要 `access.roles.read`；backend health 本身不代替授权 |
| `/operations/points` | 管理员积分调整 command 表单和结果 | `POST /admin/points/adjust` | `points.adjust` |

### 7.3 暂不注册的路由和未完成页面

| 旧目标 | 暂不注册原因 | 进入菜单的前置合同 |
| --- | --- | --- |
| `/` | Admin summary endpoint 当前不存在；不能在前端并行请求多个 capability 再猜测状态 | 显式 summary readmodel DTO 和最终 `admin.summary.read` 权限 |
| `/identity/oidc-clients` | 当前只有 OIDC 协议端点，没有管理员 client/grant/session/key 管理 API | client CRUD、grant/session 查询、secret 一次展示、key rotation 状态和权限 |
| `/operations/notifications` | 当前 OpenAPI 没有 notification delivery/failure/retry API | delivery 列表、失败详情、显式恢复 command、分页和权限 |
| `/operations/payments` | 当前只有按 order id 退款 command，无法发现订单 | orders/receipts/refunds 列表和详情、`payments.read`、退款结果查询 |
| `/operations/points/ledger` | 已补管理员积分账本查询合同 | `GET /admin/points/ledger` 的余额、桶和账本分页，`points.read` |
| `/content/assets` | assets 管理不属于 content；旧路径保持未注册 | `/system/assets` |

这些路径可以在计划中保留产品位置，但在 backend snapshot 完成前不得添加 placeholder route、菜单项或 mock DataTable。

## 8. 菜单组规划

菜单是 `src/navigation/menu.ts` 的显式静态清单，`visibility.ts` 只根据已加载的 `/me` capability 过滤。父组没有可见子项时整体隐藏。

| 菜单组 | 菜单项 | 路由 | 显示条件 |
| --- | --- | --- | --- |
| Home | Overview | `/` | P7 完成 summary 合同后显示；使用最终 `admin.summary.read` capability |
| Identity | Users | `/identity/users` | `identity.users.read` |
| Identity | Roles & Permissions | `/identity/roles` | `access.roles.read` |
| Identity | Capability Catalog | `/identity/capabilities` | `access.roles.read` |
| Content | Articles | `/content` | `content.read` |
| Content | Taxonomy | `/content/taxonomy` | `taxonomy.read` |
| System | Settings | `/system/settings` | `settings.read` |
| System | SEO | `/system/seo` | `settings.read` |
| System | Audit Log | `/system/audit` | `audit.read` |
| System | Assets | `/system/assets` | `assets.read` |
| System | Diagnostics | `/system/diagnostics` | `access.roles.read`，或后端登记的 diagnostics read capability |
| Operations | Points Adjustment | `/operations/points` | `points.adjust` |

菜单实现要求：

- 不把 `src/demo/routes.ts` 或 `src/demo` 的任何菜单合入生产清单。
- 不使用 `/admin/capabilities` 返回值创建菜单；它只能用于 capability 目录和调试展示。
- 菜单隐藏不等于授权；深链接仍经过 route guard，API 仍处理最终 403。
- 某个操作只有写权限而没有读权限时，不显示空页面入口；写按钮只能出现在已加载的资源详情页中。
- payment、notification、OIDC client 等未完成合同的菜单项不显示“即将推出”占位入口。

## 9. 页面与 Sakai/PrimeVue kit 组件规划

`src/demo/pages/uikit/` 和 `src/demo/pages/Crud.vue` 是组件用法参考。生产页使用同一套 PrimeVue 5 和 Tailwind PrimeUI，不引入第二套 UI 框架。

| 页面 | 页面结构 | 首选 kit 组件 |
| --- | --- | --- |
| Login/Callback/Error | 独立认证壳、状态反馈、回到目标页 | `Card`、`InputText`、`Password`、`Button`、`Message`、`ProgressSpinner`、`Toast`、`FloatingConfigurator` |
| Dashboard | summary 卡片、状态分布、最近失败和链接 | `Card`、`Skeleton`、`Tag`、`Message`、`Divider`、`Chart`；禁止前端并行猜测多个 capability 状态 |
| Users list | Toolbar、状态过滤、分页 DataTable、行操作 | `Toolbar`、`DataTable`、`Column`、`Select`、`InputText`、`Tag`、`Button`、`Paginator` 或 DataTable paginator、`Drawer` |
| User detail | 只读身份卡片、状态、敏感操作 | `Card`、`Panel`、`Tabs`、`Avatar`、`Tag`、`Button`、`ConfirmPopup`/`ConfirmDialog`、`Textarea` reason |
| Roles | 角色列表、创建 Dialog、capability keys、assign/revoke | `DataTable`、`Column`、`Dialog`、`InputText`、`Textarea`、`MultiSelect`、`Checkbox`、`Tag`、`Toast` |
| Capabilities | 权限 key 只读表和搜索 | `Card`、`DataTable`、`Column`、`IconField`、`InputText`、`Tag`、`Skeleton` |
| Content list | all content types、type/status filter、稳定分页、pin/status/actions | `Toolbar`、`DataTable`、`Column`、`Select`、`InputText`、`Tag`、`Button`、`Skeleton`、`Drawer` |
| Content editor | 基础字段、body、受控 data schema、schedule、pin、workflow | `Card`、`Panel`、`Tabs`、`InputText`、`Textarea` 或已批准的 `Editor`、`DatePicker`、`Select`、`InputNumber`、`ToggleSwitch`、`MultiSelect`、`Button`、`ConfirmDialog` |
| Content references | 引用列表和替换目标 | `Panel`、`DataTable`/`Listbox`、`InputText`、`Textarea`、`Button`、`ConfirmPopup` |
| Taxonomy | dimension tabs、flat terms、create/edit/archive、assignment | `Tabs`、`DataTable`、`Column`、`Dialog`、`InputText`、`Textarea`、`Tag`、`Button`、`ConfirmDialog`；不使用 Tree，因为 taxonomy 合同是平面多维标签 |
| Assets | stable reference 列表、外部引用、上传 intent、metadata | `FileUpload`、`Dialog`、`ProgressBar`、`InputText`、`Textarea`、`Message`；二进制直接传 provider upload URL，不传给 API body |
| Settings/SEO | group card、版本、受控字段、reset | `Card`、`Panel`、`Tabs`、`InputText`、`Textarea`、`InputNumber`、`ToggleSwitch`、`Select`、`Button`、`ConfirmDialog`、`Message` |
| Audit | server-side filters、分页、详情 drawer | `Toolbar`、`DatePicker`、`InputText`、`Select`、`DataTable`、`Column`、`Tag`、`Drawer`、`Timeline`、`ScrollPanel` |
| Diagnostics | health、manifest capability、错误/不可用状态 | `Card`、`Panel`、`Tag`、`ProgressBar`、`Message`、`DataTable`、`Skeleton`、带 refresh icon 的 `Button` |
| Points adjustment | subject/program/amount/reason/idempotency 表单和返回流水 | `Card`、`InputText`、`InputNumber`、`Textarea`、`Button`、`ConfirmDialog`、`Message`、`Toast`、`Tag` |
| Payments future | 订单 DataTable、退款 Dialog、状态/金额展示 | `DataTable`、`Column`、`Tag`、`Dialog`、`InputNumber`、`Textarea`、`ConfirmDialog`、`Toast`；前置是订单读 API |

通用交互规则：

- 列表页采用 `Toolbar + DataTable + server pagination + PageState`，不复制 demo 的本地数组 CRUD。
- 表单错误使用 `Message` 或字段级错误；保留后端安全 message 和 request ID，不展示堆栈或原始 provider payload。
- 删除、封禁、解封、归档、purge、publish、退款、积分调整、settings reset 和 role revoke 统一使用二次确认。
- 编辑表单提交 `expected_version` 时必须处理 409/版本冲突，提示刷新或重新载入，不覆盖他人修改。
- schedule 的界面使用用户选择的时区，提交前转成带 offset 的 RFC 3339；后端保存 UTC。
- page 不显示 category/tag assignment；post 才显示 taxonomy 控件。
- content 列表按后端返回的置顶排序展示，前端不再次拼接 pinned 区。
- Asset URL 是短时结果，不进入 Pinia、localStorage、URL 或长期页面状态。

## 10. 页面实施批次

### P0：合同和基线冻结

工作：

- 以当前 `openapi.json` 重新生成 endpoint/schema inventory，记录 operationId、response、权限和页面归属。
- 把本计划中确认的路线、权限、缺口同步到对应 `context/spec/`；旧页面名称不再作为事实来源。
- 为 route meta、菜单能力过滤、生成类型无漂移和 demo 生产剔除写失败测试。
- 先为缺失的 summary、content schema metadata、OIDC admin、notification 和 payments read API 建立后端合同任务；points read API 已进入 OpenAPI 合同，不提前创建流水页面。

退出门：OpenAPI inventory、权限清单、菜单清单和缺口清单一致；所有过时页面均有“实现/阻塞/删除”结论。

### P1：Sakai kit TS parity 和生产壳

工作：

- 对照 `src/demo/` 和 Sakai upstream，确认 layout、theme、responsive menu、dark mode、form/table/overlay/chart 样式完整迁移。
- 保持 `AppLayout`、Topbar、Sidebar、Menu、Footer、Configurator 的行为一致；不把 demo widget 误当业务组件。
- 把 Login/Access/Error 中的演示图片和假链接替换为生产可用 asset 或稳定错误状态。
- 建立 `PageState`、`ApiErrorMessage`、`ConfirmAction`、`PagedTable` 等最少共享组件。

退出门：桌面/移动端布局、暗色模式、菜单折叠、overlay 外点关闭、表单/表格/浮层样式通过 component tests 和浏览器验收。

### P2：类型化 API 和 OIDC session

工作：

- 重写 `api/client.ts` 和各 domain adapter，去除宽泛 payload 入口。
- 实现 Discovery、PKCE、state、nonce、callback、`/me`、401 单飞和 RP-Initiated Logout。
- 配置 first-party client 的 exact redirect/post logout URI；开发 proxy 不带入 production config。
- 实现 loading/anonymous/authenticated/expired/error session 状态，而不是只用 `accessToken !== null` 判断。

退出门：真实 OIDC provider 登录、拒绝授权、错误 callback、刷新重授权、logout、过期 token、401/403 和回跳深链接均有 Playwright 用例。

### P3：路由、守卫和导航

工作：

- 新建 `public-routes.ts`、`app-routes.ts`、`meta.ts`，删除旧 `/pages/empty` 和 demo 业务路由。
- 用 capability 过滤菜单，确保隐藏空父组；所有深链接和未授权入口由 guard 处理。
- 只注册当前合同可用的路由；blocked route 不加入 `router`，更不能指向 Placeholder。

退出门：无 session、缺 capability、403、404、登录态访问 login、刷新深链接和移动端菜单路径全部稳定。

### P4：Identity 和 Access

工作：

- Users list/detail：server pagination、status filter、ban/unban/delete、reason 和确认。
- Roles：list/create、capability catalog、assign/revoke；不可用的 role update/delete 不做假按钮。
- 每个 action 按独立 capability 显示，后端 403 仍正常处理。

退出门：用户分页一致性、状态变迁、删除确认、角色创建、角色授权/撤销、权限负向测试和审计结果可验证。

### P5：Content、Taxonomy 和 Assets

工作：

- 一个 ContentList 展示所有内容类型；`type_name` 仅作为同一页面的可选过滤条件。
- ContentEditor 接入 create/get/update、expected version、submit/reject/schedule/unschedule/publish/archive/restore/pin/purge。
- 接入 references 和 taxonomy assignment；page 永不显示 taxonomy 控件。
- 先实现基础字段和状态流转；完整受控 `data` 表单必须等待 content type metadata 合同，不得用任意 JSON 输入假装完成。
- taxonomy 使用 flat dimension/term UI；编辑器通过 target assignments GET 读取现有 assignments；assets 管理页只展示稳定引用，不伪造媒体库。
- upload intent -> provider upload URL -> finalize 的状态机可恢复，过期/取消/重复 finalize 有清晰反馈。

退出门：内容状态机、时区、版本冲突、置顶分页、引用替换/purge、taxonomy 选择限制、page 无 taxonomy、upload workflow 真实 E2E 通过。

### P6：Settings、SEO、Audit、Diagnostics

工作：

- Settings group list/detail 使用 `version` 和 `expected_version`；reset 必须确认。
- SEO 作为固定 `seo` group 的产品入口，站点级默认值不混入内容单页 SEO。
- Audit 完成全部 server-side filters、分页、详情安全展示。
- Diagnostics 展示 readiness、manifest capabilities 和明确的 unavailable/error 状态，不把 health 当授权成功。

退出门：setting 并发冲突、reset、敏感字段不回显、审计过滤/分页和 health 不可用场景通过。

### P7：后端合同补齐后的扩展页

仅在后端先完成规格、失败测试、实现、OpenAPI snapshot/hash 后开发：

- Admin summary DTO -> Dashboard。
- Content type/schema metadata -> 完整 post/page data 表单。
- Subject grants read -> User detail role tab。
- OIDC clients/grants/sessions/key rotation -> OIDC Clients。
- Notification delivery/failure/recovery -> Notifications。
- Payment order/receipt/refund readmodel -> Payments。
- Points account/ledger readmodel -> Points ledger。
- Asset list/search/reference checks -> 独立 Assets 页面（若产品仍需要）。

退出门：每个扩展页都有真实 read/write endpoint、权限、错误、分页/版本语义和 E2E；没有“先画 UI 等接口”的分支。

### P8：清理、生产构建和上线

工作：

- 先对当前 dev 基线创建可追溯 tag，再从通过验收的 release commit 构建；发布分支不继承 dev-only 功能。
- 删除 `src/demo/`、`src/demo/routes.ts`、demo services、demo widgets、未使用的 `public/demo/data` 和 demo-only images。
- 删除 `import.meta.env.DEV` demo 路由/菜单分支、`VITE_DEV_AUTH`、静态 mock 开关和测试 secret。
- 删除旧 Placeholder、Empty、Sakai demo dashboard/landing/blocks/uikit 生产入口及所有引用。
- 运行 `npm ci`、生成 API 类型、format/lint、typecheck、unit、production build 和真实后端 Playwright。
- 只发布 `npm run build` 产出的静态文件，由 Caddy/Nginx/对象存储/CDN 或批准的静态服务器提供；生产不运行 `vite` 或 `vite preview`。
- 配置 SPA fallback、immutable hashed assets、sourcemap 策略、CSP、缓存、security headers、API origin、CORS allowlist 和 OIDC redirect URI。

退出门：生产 bundle 无 demo/mock/dev endpoint/token/secret；刷新任意受保护深链接仍能 fallback 后由 Vue Router 接管；发布环境不会读取当前 dev 分支配置。

## 11. 测试矩阵

| 层级 | 必测内容 |
| --- | --- |
| API adapter unit | operationId 映射、query/header/body、204、Page DTO、request ID、错误归一化、AbortSignal、idempotency key |
| Auth unit | PKCE、state/nonce、callback 错误、内存 token、storage 禁止 bearer、401 单飞、logout 清理 |
| Router unit | auth redirect、safe redirect、capability deny、public route、404、title、blocked route 不注册 |
| Navigation unit | capability 过滤、父组隐藏、无 API 动态菜单、动作按钮单独过滤 |
| Component unit | loading/empty/error、表单字段错误、确认、版本冲突、分页 query、timezone offset、dirty form |
| Architecture check | 页面不直连 fetch、业务不依赖 demo service、无手写 backend DTO、生产 route 无 demo 引用 |
| Real backend E2E | OIDC 登录/logout、刷新深链、用户 ban/unban/delete、角色授权、内容全状态、taxonomy、settings、audit、points、assets |
| Negative E2E | 401、403、过期 session、重复 idempotency key、409 version、错误 request ID、无权限深链 |
| Build audit | `npm ci`、generated type 无漂移、typecheck/lint/build、bundle 无 demo/mock/dev config |

Playwright 必须连接真实后端和测试 OIDC provider；MSW 或静态 JSON 只允许在显式 unit/mock profile 使用，不能替代发布验收。

## 12. 上线完成定义

只有同时满足以下条件才发布管理员 SPA：

- 生产路由和菜单只来自本计划已完成的 OpenAPI 合同；没有 Placeholder 伪装完成。
- OIDC Code + PKCE、内存 token、`/me` capability、401/403/登出行为通过真实 E2E。
- 后端授权仍是最终边界，前端隐藏规则和 route guard 仅作为 UX 层。
- API 类型、OpenAPI snapshot/hash、adapter、页面和测试无漂移。
- 所有当前上线页面具备 loading、empty、error、permission denied、validation 和 request ID 展示。
- sensitive action 有确认、reason/idempotency/version 处理，secret 和 token 不进入浏览器持久化和日志。
- `src/demo/`、demo routes、mock services、dev auth bypass、旧壳 placeholder 和无引用 demo assets 已删除。
- production build 不包含开发 endpoint、MSW/mock worker、测试 secret 或当前 dev 分支专属代码。
- 静态文件服务、SPA fallback、CSP、CORS、缓存和 OIDC origin 配置已在生产形态实测。
- 质量门和空环境端到端门按照 `context/spec/quality-release.md` 完成，并留存实际命令及结果。

## 13. 需要在实施前确认的决策门

| 决策 | 默认处理 | 未确认时的影响 |
| --- | --- | --- |
| Admin summary operation | 增加显式 summary readmodel DTO，Dashboard 禁止前端拼接多个 service | Dashboard 不进入生产菜单 |
| Content type metadata | 增加显式类型/schema metadata 合同，生成受控字段表单 | 只能先验收基础字段，不能完成完整内容编辑 |
| OIDC client admin | 新增 admin OIDC client/grant/session/key read/write API | `/identity/oidc-clients` 不注册 |
| Payment admin read | 新增 orders/receipts/refunds readmodel 和 `payments.read` | 只有退款 command，不能上线 Payments DataTable |
| Points admin read | 使用 `GET /admin/points/ledger` 的 account/ledger query 和 `points.read` | 只上线单次调整表单，流水页仍待前端页面施工 |
| Assets standalone page | 新增 list/search/reference API，或明确仅嵌入业务表单 | 不做媒体库，不保留旧媒体页面 |
| Admin notifications | 新增 delivery/failure/recovery API 和稳定权限 | 不保留 Notifications 菜单 |
| OIDC 客户端实现 | ✅ 2026-08-10 采用 `oidc-client-ts` 3.5（Apache-2.0）处理 Discovery/PKCE/state/callback/logout，替代手写协议；`userStore` 用内存 WebStorageStateStore、`stateStore` 用 sessionStorage、不请求 `offline_access`、关闭 silent renew，满足 admin.md §3 全部约束 | 弃选：@openid/appauth 停更；oidc-spa 默认持久化且倾向 Keycloak/BFF；keycloak-js 绑定 Keycloak |
| SPA 长会话 | 首版刷新重新走 OP session | 不在 SPA 增加 refresh token 存储；如需无跳转必须另立 BFF 合同 |
| dev 分支处置 | 先打归档 tag，发布分支清除 dev-only 代码和配置 | 当前 dev 分支不能作为生产构建输入 |
