# 管理员 UI Kit 规格（Sakai Vue）

## 1. 定位

`admin/` 是纯前端 Vue 3 SPA 界面基线，上游为 PrimeFaces Sakai Vue（https://github.com/primefaces/sakai-vue，MIT 许可证）。本仓库将它作为 aiya-cms 管理端 SPA 的 UI kit 使用：布局壳、主题体系、组件清单和页面骨架直接复用；业务页面按 `admin.md` 契约接入 OpenAPI，不在此 kit 内维护业务逻辑。

2026-08 起 admin 已 TS 化：旧 JS 实现（`js-src/`）整体删除，demo 画廊全量 TS 化迁入 `src/demo/`（仅开发路由，生产构建剔除），当前代码基线为 `src/`（TypeScript）。迁移与业务化阶段见 `../admin-ts-migration-plan.md`。

本规格是 UI kit 内容与版本的事实清单，供业务页面开发时查用。组件与页面的增删必须同步更新本规格。

## 2. 依赖版本（2026-08 升级基线）

| 包 | 版本 | 说明 |
| --- | --- | --- |
| vite | 8.2.1 | 构建工具 |
| @vitejs/plugin-vue | 6.0.8 | Vue SFC 插件 |
| @tailwindcss/vite | 4.3.3 | Tailwind CSS v4 插件 |
| tailwindcss | 4.3.3 | 原子样式 |
| tailwindcss-primeui | 0.6.1 | PrimeVue 主题 CSS 变量 ↔ Tailwind 工具类桥接 |
| vue | 3.5.41 | 框架 |
| vue-router | 5.2.0 | 路由 |
| primevue | 5.0.0 | UI 组件库（按需自动导入，214 个导出） |
| @primeuix/themes | 3.0.0 | Aura/Lara/Nora 主题 preset 与 `updatePreset`/`updateSurfacePalette` |
| primeicons | 8.0.0 | 图标字体（`pi pi-*`） |
| chart.js | 4.5.1 | `Chart` 组件的底层图表库 |
| oidc-client-ts | 3.5.0 | OIDC 客户端（Discovery/PKCE/state/callback/logout），见 `admin.md` §3 |
| @primevue/auto-import-resolver | 5.0.0 | 组件自动导入解析器 |
| unplugin-vue-components | 32.1.0 | 按需自动导入（`dts: 'src/components.d.ts'`） |
| typescript | 5.9.3 | 语言（7.x 与 typescript-eslint/openapi-typescript peer 冲突，暂锁 5.x） |
| vue-tsc | 3.3.9 | SFC 类型检查（`vue-tsc -b`） |
| @vue/tsconfig / @tsconfig/node24 | 最新 | tsconfig 基准 |
| typescript-eslint | 最新 | ESLint TS 支持 |
| sass | 1.102.0 | SCSS 编译（Vite 8 默认 modern-compiler） |
| eslint | 10.8.0 | flat config（`eslint.config.ts`，需 jiti） |
| eslint-plugin-vue | 10.10.0 | `flat/essential`；`vue/component-tags-order` 已改为 `vue/block-order` |
| @vue/eslint-config-prettier | 10.2.0 | Prettier 规则桥接 |
| @eslint/js / globals | 最新 | flat config 基础与全局变量 |
| openapi-typescript | 7.13.0 | OpenAPI → TS 类型生成（`npm run generate:api`） |
| prettier | 3.9.6 | 格式化 |

- `src/assets/` 是 git 子模块（primefaces/sakai-assets），承载布局 SCSS；升级不触及子模块内容。
- npm scripts：`dev`（vite）、`build`（vue-tsc -b && vite build）、`typecheck`、`preview`（仅开发演示用，生产禁止，见 `admin.md` §8）、`lint`（eslint --fix .）、`test`（vitest run，见 §7）、`generate:api`（openapi-typescript ../openapi.json -o src/api/schema.d.ts）。

## 3. 架构与装配机制

- 组合根：`src/main.ts` 注册 `router`、`PrimeVue`（Aura preset，`darkModeSelector: '.app-dark'`）、`ToastService`、`ConfirmationService`。
- 组件解析：`vite.config.ts` 用 `unplugin-vue-components` + `PrimeVueResolver`（自动生成 `src/components.d.ts`），模板里直接写 PascalCase 标签即可。
- 主题：`src/layout/composables/layout.ts` 的 `useLayout()` 提供 `layoutConfig`（preset/primary/surface/darkTheme/menuMode）与 `layoutState`（菜单折叠、激活项等），以及 `toggleDarkMode`/`toggleMenu`/`changeMenuMode`/`isDesktop` 等；导出 `MenuItem` 类型供导航清单使用。
- 主题面板：`AppConfigurator.vue` 支持 3 个 preset（Aura/Lara/Nora）、17 个 primary 色板（含 noir）、8 个 surface 色板（slate/gray/zinc/neutral/stone/soho/viva/ocean）、暗色模式、static/overlay 两种菜单模式。
- 样式入口：`src/assets/tailwind.css`（Tailwind v4 + `@plugin 'tailwindcss-primeui'` + 自定义 breakpoint）和 `src/assets/styles.scss`（primeicons + `layout/` 子模块 + `demo/`）。
- 图表配色读取 CSS 变量（`--p-primary-*`、`--surface-border`、`--text-color-secondary`），并随主题切换响应更新。
- API 类型：`src/api/schema.d.ts` 由 `npm run generate:api` 生成，禁手工修改；`src/api/client.ts` 为 fetch 封装（鉴权头、`ApiError{status,body,requestId}`、401 回调、204 void）。

## 4. UI 组件清单

### 4.1 Kit 自有组件（已 TS 化，位于 `src/`）

| 组件 | 路径 | 用途 |
| --- | --- | --- |
| AppLayout | `src/layout/AppLayout.vue` | 布局壳：Topbar + Sidebar + 主区 router-view + Footer + Toast |
| AppTopbar | `src/layout/AppTopbar.vue` | 顶栏：菜单按钮、Logo、暗色切换、主题面板入口 |
| AppSidebar | `src/layout/AppSidebar.vue` | 侧边栏容器（含 overlay 外点关闭） |
| AppMenu | `src/layout/AppMenu.vue` | 侧边菜单 model（产品显式导航清单：Dashboard/Content/Community/Users/System/Settings） |
| AppMenuItem | `src/layout/AppMenuItem.vue` | 递归菜单项（支持多级、icon、active 态） |
| AppFooter | `src/layout/AppFooter.vue` | 页脚 |
| AppConfigurator | `src/layout/AppConfigurator.vue` | 主题配置面板（preset/primary/surface/暗色/菜单模式） |
| FloatingConfigurator | `src/components/FloatingConfigurator.vue` | 独立页（Login/404 等）用的浮动主题按钮组 |

`useLayout()` composable 是布局与主题状态的唯一前端入口，业务页不得另建平行状态。

demo 画廊组件位于 `src/demo/components/`（仅开发路由 `/demo/**`，生产剔除）：BlockViewer、dashboard 5 个 widget、landing 6 个 widget。

### 4.2 PrimeVue 组件（kit 已演示，按类别；演示代码在 `src/demo/pages/uikit/`，仅开发路由）

| 类别 | 组件 | 演示页 |
| --- | --- | --- |
| Form | AutoComplete, Checkbox, ColorPicker, DatePicker, FloatLabel, IconField, InputGroup, InputGroupAddon, InputIcon, InputNumber, InputText, Knob, Listbox, MultiSelect, RadioButton, Rating, Select, SelectButton, Slider, Textarea, ToggleButton, ToggleSwitch, TreeSelect, Fluid | InputDoc |
| 按钮 | Button, ButtonGroup, SplitButton | ButtonDoc |
| 数据表 | DataTable, Column | TableDoc |
| 数据视图 | DataView, OrderList, PickList, Tag | ListDoc |
| 树 | Tree, TreeTable | TreeDoc |
| 面板 | Accordion(+Panel/Header/Content), Card, Divider, Fieldset, Panel, Splitter(+Panel), Tabs(TabList/Tab/TabPanels/TabPanel), Toolbar | PanelsDoc |
| 浮层 | Dialog, Drawer, Popover, ConfirmPopup | OverlayDoc |
| 菜单 | Breadcrumb, ContextMenu, MegaMenu, Menu, Menubar, PanelMenu, TieredMenu, Stepper(StepList/Step) | MenuDoc |
| 媒体 | Carousel, Galleria, Image | MediaDoc |
| 消息 | Message, Toast | MessagesDoc、FileDoc |
| 文件 | FileUpload | FileDoc |
| 图表 | Chart（chart.js 4） | ChartDoc |
| 杂项 | Avatar, AvatarGroup, Badge, Chip, OverlayBadge, ProgressBar, ScrollPanel, ScrollTop, Skeleton | MiscDoc |
| 时间轴 | Timeline | TimelineDoc |
| 服务/指令 | ToastService, ConfirmationService（main.ts 注册）；`v-styleclass`（StyleClass 指令，顶栏浮层开关） | — |

### 4.3 已安装但未在 demo 中演示、可直接按需使用的组件

primevue 5.0.0 全部 214 个导出均经自动导入解析器可用，常见未演示项：CascadeSelect、CheckboxGroup、RadioButtonGroup、InputMask、InputOtp、InputTags、InputColor、Editor、Inplace、MeterGroup、OrganizationChart、ProgressSpinner、Sidebar、SpeedDial、Steps、Terminal、VirtualScroller、BlockUI、DeferredContent、Ripple、Tooltip、DialogService、DynamicDialog、CommandMenu、Compare/ImageCompare、Label、KeyFilter。使用前查 PrimeVue 5 文档确认 API，不以 demo 页用法为准。

### 4.4 数据服务（demo 专用，仅开发路由消费）

`src/demo/services/`：ProductService、CustomerService、CountryService、NodeService、PhotoService；对应 `public/demo/data/*.json`。均为静态 mock，业务页面必须改为消费 `src/api/schema.d.ts` 生成的类型化 adapter（`admin.md` §2）。

## 5. 页面清单（路由）

生产路由和菜单以 `admin.md` 为事实清单。`src/router/meta.ts` 使用 `titleKey/requiresAuth/requiredCapability/shell`；`src/navigation/menu.ts` 使用 `labelKey`，显示文本统一由 Vue I18n 解析。公共认证路由包含 login、register、verify-email、password-reset request/confirm、callback、logged-out、access-denied、error 和 404。

业务主路由固定为 `/dashboard`、`/content/write|articles|taxonomies|comments`、`/community/discussions|tags`、`/users`、`/system/audit|operations|assets`、`/settings`，其余目标在对应后端合同和真实页面完成后显式注册。community discussions 使用 Drawer 承载详情/审核/lock/archive，community tags 使用独立 DataTable/Dialog；两者不得复用 content/taxonomy adapter。详情/编辑按 `admin.md` §4.2 使用 Drawer/Dialog，不创建 record detail 子路由，不用 Placeholder 假装完成。

共享业务壳位于 `src/components/shell/`：`PageShell`、`SurfaceCard`、`EntityDrawerShell`、`FormDialogShell`、`SensitiveActionDialog`。现有 `PageToolbar` 在迁移完成后删除，业务页面不得同时维护两套标题壳。

demo 画廊页面位于 `src/demo/pages/`（仅开发路由 `/demo/**`，生产剔除）：uikit 15 个演示页、`Blocks.vue`、`Crud.vue`（业务列表 CRUD 参照模板）、`Documentation.vue`、`Landing.vue`、`Dashboard.vue`。Crud 模板要点：Toolbar（新建/批量删除/导出）+ DataTable（全局过滤/分页/CSV/多选）+ Dialog 表单 + 确认删除。

## 6. 业务化约定

- 管理员端显示名称固定为大写 `AIYA-CMS`（`src/env.ts` 的 `APP_NAME`），用于顶栏、页脚、页面标题和认证页文案；不使用动态站点名或品牌资源。

- 保留 `admin/LICENSE.md`（MIT）与 `admin/UPSTREAM.md`（来源说明）；重构业务页面不得移除归属信息。
- 侧边导航清单在 `src/navigation/menu.ts` 显式配置（`admin.md` 为事实清单），`visibility.ts` 按管理员 session capability 与已注册路由过滤并递归隐藏空分组；`src/layout/AppMenu.vue` 只渲染过滤结果。demo 分组仅开发构建可见。
- 新增业务页面使用 kit 已演示的组件组合（列表 CRUD 参照 `src/demo/pages/Crud.vue`），表单参照 `src/demo/pages/uikit/InputDoc.vue` 的组件用法；禁止引入平行 UI 框架。
- Settings 表单只消费生成 OpenAPI 的 `SettingGroupDTO.fields`、`values` 和已校验 metadata；`src/components/forms/setting-fields.ts` 按 `Field.type` 将 `bool`、`text`、`textarea`、`select`、`radio`、`mult`、`upload` 分别映射到 `ToggleSwitch`、`InputText`、`Textarea`、`Select`、`RadioButton`、`MultiSelect`、`FileUpload`，不得为具体设置 slug 编写独立表单分支。上传流程只能通过资产 opaque ID adapter 注入，不能把二进制或 signed URL 写入 settings。
- Users 列表的“积分管理”操作使用右侧 `Drawer` 读取 `GET /api/v1/admin/points/ledger` 的余额、桶和分页流水，并调用 `POST /api/v1/admin/points/adjust`；表单提交 signed amount、reason、幂等键和可选 program，省略 program 时使用 `credit`，不提交 bucket ID。桶路由遵循 points 后端规则：正数进入 perpetual，负数 FIFO 扣除 expiring/perpetual 桶。
- 主题与暗色模式通过 `useLayout()`/AppConfigurator 提供；业务页不得绕过它直接改 CSS 变量。
- `src/demo/` 是 demo 画廊（仅开发路由，生产构建剔除）：修改组件用法只读参考，不在其中改业务代码；kit parity 和业务验收完成后按 `context/admin-ts-migration-plan.md` P8 整体删除。
- 升级依赖后必须执行 `npm ci`（不得 `--force`）、`npm run typecheck`、`npm run lint`、`npm run build` 全绿（`admin.md` §9）。

## 7. 测试约定（P0 合同门）

`npm run test`（vitest，`src/tests/`）守护迁移基线：

- 生产路由 meta 合同与阻塞路由不注册（`unit/router-meta.test.ts`）。
- 菜单 capability/路由注册过滤与空父组隐藏（`unit/menu-visibility.test.ts`）。
- 生成类型无漂移：`openapi.sha256` 校验与 `schema.d.ts` 重新生成对比（`unit/type-drift.test.ts`）。
- demo 生产剔除：生产路由/菜单无 demo 引用，demo 只允许被 DEV 守卫的 router 入口导入（`unit/demo-exclusion.test.ts`）。
- 共享组件与 api 基础单元测试（`components/`、`unit/api-core.test.ts`）。
- Settings 字段 registry 和 settings/audit 页面路由合同测试（`unit/setting-fields.test.ts`、`unit/router-meta.test.ts`）。
- OIDC 会话约束测试：scope 不含 `offline_access`、silent renew 关闭、userStore 不触 web storage、callback 路径精确匹配、登录表单参数完整、session 状态机与 401 单飞（`unit/oidc-config.test.ts`、`unit/login-form.test.ts`、`unit/session.test.ts`、`unit/unauthorized.test.ts`）。
