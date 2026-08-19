# context/ — 唯一规格来源

`context/` 是当前唯一权威规格集合。后端规格位于 `context/spec/`，用户站规格与设计位于 `context/user site spec/`，管理员端规格位于 `context/admin dash spec (SPA)/`。代码、测试、迁移、OpenAPI、两端前端和 Compose 与规格不一致时，先更新对应 owner 的规格，再写失败测试，最后修改实现。

本地 Demo 的旧重构施工计划已从工作树移除；历史由 Git 保留。目录分离只用于明确后端、用户站和管理员端的文档所有权，不形成第二套长期事实源。用户站 `IMPLEMENTATION.md` 是本次目标规格的稳定迁移顺序与验收合同，不记录进度、排期或负责人。

## 阅读顺序

1. [`spec/architecture.md`](spec/architecture.md)：分层、依赖、数据所有权和副作用红线。
2. [`spec/composition.md`](spec/composition.md)：manifest、注册表、Port/adapter 和启动生命周期。
3. [`spec/kernel/README.md`](spec/kernel/README.md)：技术内核范围，再按其中索引阅读细分规格。
4. [`spec/capabilities/README.md`](spec/capabilities/README.md)：能力统一合同，再按需求阅读单项能力。
5. [`spec/adapters.md`](spec/adapters.md)：外部 Port 实现库（`inc/adapters`），按 capability 分目录组织，可被 api 与 feature 使用。
6. [`spec/features.md`](spec/features.md)：跨能力垂直业务流。
7. [`spec/http-openapi.md`](spec/http-openapi.md)：HTTP、授权、分页和 OpenAPI。
8. [`user site spec/README.md`](<user site spec/README.md>)：用户站规格与设计案入口及文档职责。
9. [`user site spec/user-site.md`](<user site spec/user-site.md>)：Astro SSR、Markdown 安全渲染、SEO/head、BFF 会话、feature 消费与用户侧端点。
10. [`user site spec/LAYOUT.md`](<user site spec/LAYOUT.md>)：用户站页面结构、信息优先级和响应式布局。
11. [`user site spec/DESIGN.md`](<user site spec/DESIGN.md>)：用户站视觉语言、Design Tokens 和组件元素。
12. [`user site spec/IMPLEMENTATION.md`](<user site spec/IMPLEMENTATION.md>)：现有实现迁移到目标用户站的删除清单、依赖顺序、测试矩阵和完成定义。
13. [`admin dash spec (SPA)/admin.md`](<admin dash spec (SPA)/admin.md>)：管理员端认证、契约和部署。
14. [`admin dash spec (SPA)/admin-uikit.md`](<admin dash spec (SPA)/admin-uikit.md>)：管理员 UI kit（Sakai Vue）组件与页面清单。
15. [`spec/quality-release.md`](spec/quality-release.md)：跨后端、用户站与管理员端的测试矩阵、迁移和发布门。

## 文档规则

- 三个规格目录按 owner 分工，不复制相同合同；本目录不维护 ADR、roadmap 或重复的执行状态文档。
- `MUST/必须` 是发布硬约束，`SHOULD/应当` 允许有测试和说明支持的例外，`MAY/可以` 是可选实现。
- Capability、Feature、Port、事件、workflow、activity、Cron、内容类型、积分行为、错误码和路由的稳定 key 必须同时出现在对应规格、代码常量与合同测试中。
- 规格描述对外可观察行为和边界，不冻结不必要的私有类名；示例代码默认是说明，不自动成为注册项。
- 禁止自动发现式装配。任何运行时能力都必须能从应用 manifest 追溯。
- 当前 Demo 无数据兼容义务；新基线发布后，迁移历史重新成为不可改写的兼容合同。

## 目录

```text
context/
  README.md
  spec/                         # 后端与跨系统发布合同
    architecture.md
    composition.md
    adapters.md
    features.md
    features/
    http-openapi.md
    quality-release.md
    kernel/
    capabilities/
  user site spec/               # Astro 用户站规格与设计案
    README.md
    user-site.md
    LAYOUT.md
    DESIGN.md
    IMPLEMENTATION.md
  admin dash spec (SPA)/        # Vue 管理员端规格
    admin.md
    admin-uikit.md
```
