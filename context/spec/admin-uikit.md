# 管理员 UI Kit 规格（Sakai Vue）

## 1. 定位

`admin/` 是纯前端 Vue 3 SPA 界面基线，上游为 PrimeFaces Sakai Vue（https://github.com/primefaces/sakai-vue，MIT 许可证）。本仓库将它作为 aiya-cms 管理端 SPA 的 UI kit 使用：布局壳、主题体系、组件清单和页面骨架直接复用；业务页面按 `admin.md` 契约接入 OpenAPI，不在此 kit 内维护业务逻辑。

本规格是 `admin/` 目录内容与版本的事实清单，供后续业务页面开发时查用。组件与页面的增删必须同步更新本规格。

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
| @primevue/auto-import-resolver | 5.0.0 | 组件自动导入解析器 |
| unplugin-vue-components | 32.1.0 | 按需自动导入 |
| sass | 1.102.0 | SCSS 编译（`api: 'modern-compiler'`） |
| eslint | 10.8.0 | flat config（`eslint.config.mjs`），已移除 `.eslintrc.cjs` |
| eslint-plugin-vue | 10.10.0 | `flat/essential`；`vue/component-tags-order` 已改为 `vue/block-order` |
| @vue/eslint-config-prettier | 10.2.0 | Prettier 规则桥接 |
| @eslint/js | 10.0.1 | `js.configs.recommended` |
| prettier | 3.9.6 | 格式化 |
| globals | 最新 | flat config 环境全局变量 |

- `src/assets/` 是 git 子模块（primefaces/sakai-assets），承载布局 SCSS；升级不触及子模块内容。
- npm scripts：`dev`（vite）、`build`（vite build）、`preview`（仅开发演示用，生产禁止，见 `admin.md` §8）、`lint`（eslint --fix .）。

## 3. 架构与装配机制

- 组合根：`src/main.js` 注册 `router`、`PrimeVue`（Aura preset，`darkModeSelector: '.app-dark'`）、`ToastService`、`ConfirmationService`。
- 组件解析：`vite.config.mjs` 用 `unplugin-vue-components` + `PrimeVueResolver`，模板里直接写 PascalCase 标签即可，无需手动 import（手动 import 亦可用）。
- 主题：`layout/composables/layout.js` 的 `useLayout()` 提供 `layoutConfig`（preset/primary/surface/darkTheme/menuMode）与 `layoutState`（菜单折叠、激活项等），以及 `toggleDarkMode`/`toggleMenu`/`changeMenuMode`/`isDesktop` 等。
- 主题面板：`AppConfigurator.vue` 支持 3 个 preset（Aura/Lara/Nora）、17 个 primary 色板（含 noir）、8 个 surface 色板（slate/gray/zinc/neutral/stone/soho/viva/ocean）、暗色模式、static/overlay 两种菜单模式。
- 样式入口：`src/assets/tailwind.css`（Tailwind v4 + `@plugin 'tailwindcss-primeui'` + 自定义 breakpoint）和 `src/assets/styles.scss`（primeicons + `layout/` 子模块 + `demo/`）。
- 图表配色读取 CSS 变量（`--p-primary-*`、`--surface-border`、`--text-color-secondary`），并随主题切换响应更新。

## 4. UI 组件清单

### 4.1 Kit 自有组件

| 组件 | 路径 | 用途 |
| --- | --- | --- |
| AppLayout | `src/layout/AppLayout.vue` | 布局壳：Topbar + Sidebar + 主区 router-view + Footer + Toast |
| AppTopbar | `src/layout/AppTopbar.vue` | 顶栏：菜单按钮、Logo、暗色切换、主题面板入口、菜单按钮 |
| AppSidebar | `src/layout/AppSidebar.vue` | 侧边栏容器（含 overlay 外点关闭） |
| AppMenu | `src/layout/AppMenu.vue` | 侧边菜单 model（硬编码导航清单，业务导航替换点） |
| AppMenuItem | `src/layout/AppMenuItem.vue` | 递归菜单项（支持多级、icon、active 态） |
| AppFooter | `src/layout/AppFooter.vue` | 页脚 |
| AppConfigurator | `src/layout/AppConfigurator.vue` | 主题配置面板（preset/primary/surface/暗色/菜单模式） |
| FloatingConfigurator | `src/components/FloatingConfigurator.vue` | 独立页（Login/404 等）用的浮动主题按钮组 |
| BlockViewer | `src/components/BlockViewer.vue` | 代码块预览/源码切换 + 复制 |
| StatsWidget | `src/components/dashboard/StatsWidget.vue` | 概览统计卡片（纯静态演示） |
| RecentSalesWidget | `src/components/dashboard/RecentSalesWidget.vue` | DataTable 最近销售（demo 数据） |
| BestSellingWidget | `src/components/dashboard/BestSellingWidget.vue` | 畅销列表 + 弹出 Menu |
| RevenueStreamWidget | `src/components/dashboard/RevenueStreamWidget.vue` | 堆叠柱状 Chart |
| NotificationsWidget | `src/components/dashboard/NotificationsWidget.vue` | 通知时间线列表 |
| TopbarWidget / HeroWidget / FeaturesWidget / HighlightsWidget / PricingWidget / FooterWidget | `src/components/landing/` | 营销落地页分段（业务不需要时删除） |

`useLayout()` composable 是布局与主题状态的唯一前端入口，后续业务页不得另建平行状态。

### 4.2 PrimeVue 组件（kit 已演示，按类别）

Demo 页位于 `src/views/uikit/`，是每个组件的参考用法：

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
| 服务/指令 | ToastService, ConfirmationService（main.js 注册）；`v-styleclass`（StyleClass 指令，顶栏浮层开关） | — |

### 4.3 已安装但未在 demo 中演示、可直接按需使用的组件

primevue 5.0.0 全部 214 个导出均经自动导入解析器可用，常见未演示项：CascadeSelect、CheckboxGroup、RadioButtonGroup、InputMask、InputOtp、InputTags、InputColor、Editor、Inplace、MeterGroup、OrganizationChart、ProgressSpinner、Sidebar、SpeedDial、Steps、Terminal、VirtualScroller、BlockUI、DeferredContent、Ripple、Tooltip、DialogService、DynamicDialog、CommandMenu、Compare/ImageCompare、Label、KeyFilter。使用前查 PrimeVue 5 文档确认 API，不以 demo 页用法为准。

### 4.4 数据服务（demo 专用，业务接入后删除）

`src/service/`：ProductService、CustomerService、CountryService、NodeService、PhotoService；对应 `public/demo/data/*.json`。均为静态 mock，业务页面必须改为消费 OpenAPI 生成的 adapter（见 `admin.md` §2）。

## 5. 页面清单（路由）

`src/router/index.js`，`createWebHistory`；除 landing/auth/notfound 外均挂在 `AppLayout` 下。

| 路由 | name | 页面 | 用途 |
| --- | --- | --- | --- |
| `/` | dashboard | `src/views/Dashboard.vue` | 概览壳（当前为 5 个静态 widget 演示；按 `admin.md` §5 改为消费 AdminSummaryProvider） |
| `/uikit/formlayout` | formlayout | `src/views/uikit/FormLayout.vue` | 表单布局演示 |
| `/uikit/input` | input | `src/views/uikit/InputDoc.vue` | 输入类组件演示 |
| `/uikit/button` | button | `src/views/uikit/ButtonDoc.vue` | 按钮演示 |
| `/uikit/table` | table | `src/views/uikit/TableDoc.vue` | DataTable 完整演示（排序/过滤/分页/展开） |
| `/uikit/list` | list | `src/views/uikit/ListDoc.vue` | DataView/OrderList/PickList 演示 |
| `/uikit/tree` | tree | `src/views/uikit/TreeDoc.vue` | Tree/TreeTable 演示 |
| `/uikit/panel` | panel | `src/views/uikit/PanelsDoc.vue` | 面板类组件演示 |
| `/uikit/overlay` | overlay | `src/views/uikit/OverlayDoc.vue` | Dialog/Drawer/Popover/ConfirmPopup 演示 |
| `/uikit/media` | media | `src/views/uikit/MediaDoc.vue` | Carousel/Galleria/Image 演示 |
| `/uikit/message` | message | `src/views/uikit/MessagesDoc.vue` | Message 演示 |
| `/uikit/file` | file | `src/views/uikit/FileDoc.vue` | FileUpload 演示 |
| `/uikit/menu` | menu | `src/views/uikit/MenuDoc.vue` | 各类菜单演示 |
| `/uikit/charts` | charts | `src/views/uikit/ChartDoc.vue` | 5 种 Chart 演示（bar/line/pie/polar/radar） |
| `/uikit/misc` | misc | `src/views/uikit/MiscDoc.vue` | 杂项组件演示 |
| `/uikit/timeline` | timeline | `src/views/uikit/TimelineDoc.vue` | Timeline 演示 |
| `/blocks/free` | blocks | `src/views/utilities/Blocks.vue` | Prime Blocks 代码块预览（BlockViewer） |
| `/pages/empty` | empty | `src/views/pages/Empty.vue` | 空白页模板 |
| `/pages/crud` | crud | `src/views/pages/Crud.vue` | CRUD 完整示例：Toolbar+DataTable（全局过滤/分页/CSV 导出/多选删除）+ Dialog 表单 + 确认删除 —— 业务列表页的参照模板 |
| `/start/documentation` | documentation | `src/views/pages/Documentation.vue` | Kit 使用说明页 |
| `/landing` | landing | `src/views/pages/Landing.vue` | 营销落地页（独立布局） |
| `/pages/notfound` | notfound | `src/views/pages/NotFound.vue` | 404 |
| `/auth/login` | login | `src/views/pages/auth/Login.vue` | 登录页模板（现为静态表单；OIDC 接入见 `admin.md` §3） |
| `/auth/access` | accessDenied | `src/views/pages/auth/Access.vue` | 403 无权限 |
| `/auth/error` | error | `src/views/pages/auth/Error.vue` | 500 错误 |

## 6. 业务化约定

- 保留 `admin/LICENSE.md`（MIT）与 `admin/UPSTREAM.md`（来源说明）；重构业务页面不得移除归属信息。
- 侧边导航清单在 `AppMenu.vue` 硬编码：业务阶段替换为按 capability 显式配置的菜单（`admin.md` §4），demo 分组（UI Components/Prime Blocks/Hierarchy/Get Started）删除。
- `src/views/uikit/` 与 `utilities/Blocks.vue` 是开发期参考页，生产构建应通过路由移除或保留于文档模式，不得影响业务 bundle 契约。
- 新增业务页面使用 kit 已演示的组件组合（列表 CRUD 参照 `pages/Crud.vue`），表单参照 `uikit/InputDoc.vue` 的组件用法；禁止引入平行 UI 框架。
- 主题与暗色模式通过 `useLayout()`/AppConfigurator 提供；业务页不得绕过它直接改 CSS 变量。
- 升级依赖后必须执行 `npm ci`（不得 `--force`）、`npm run lint`、`npm run build` 全绿（`admin.md` §9）。
