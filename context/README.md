# context/ — 唯一规格来源

`context/spec/` 是当前唯一权威规格集合。代码、测试、迁移、OpenAPI、管理员端和 Compose 与规格不一致时，先更新规格，再写失败测试，最后修改实现。

`full-rebuild-plan.md` 是本次本地 Demo 重构的一次性施工记录，不与 `context/spec/` 共同定义长期行为。若两者冲突，以已经落入 `context/spec/` 的约定为准；重构完成后可从工作树移除计划书，历史由 Git 保留。

## 阅读顺序

1. [`spec/architecture.md`](spec/architecture.md)：分层、依赖、数据所有权和副作用红线。
2. [`spec/composition.md`](spec/composition.md)：manifest、注册表、Port/adapter 和启动生命周期。
3. [`spec/kernel/README.md`](spec/kernel/README.md)：技术内核范围，再按其中索引阅读细分规格。
4. [`spec/capabilities/README.md`](spec/capabilities/README.md)：能力统一合同，再按需求阅读单项能力。
5. [`spec/features.md`](spec/features.md)：跨能力垂直业务流。
6. [`spec/http-openapi.md`](spec/http-openapi.md)：HTTP、授权、分页和 OpenAPI。
7. [`spec/admin.md`](spec/admin.md)：管理员端认证、契约和部署。
8. [`spec/admin-uikit.md`](spec/admin-uikit.md)：管理员 UI kit（Sakai Vue）组件与页面清单。
9. [`spec/quality-release.md`](spec/quality-release.md)：测试矩阵、迁移和发布门。

## 文档规则

- 本目录不维护 ADR、roadmap 或重复的执行状态文档。
- `MUST/必须` 是发布硬约束，`SHOULD/应当` 允许有测试和说明支持的例外，`MAY/可以` 是可选实现。
- Capability、Feature、Port、事件、workflow、activity、Cron、内容类型、积分行为、错误码和路由的稳定 key 必须同时出现在对应规格、代码常量与合同测试中。
- 规格描述对外可观察行为和边界，不冻结不必要的私有类名；示例代码默认是说明，不自动成为注册项。
- 禁止自动发现式装配。任何运行时能力都必须能从应用 manifest 追溯。
- 当前 Demo 无数据兼容义务；新基线发布后，迁移历史重新成为不可改写的兼容合同。

## 目录

```text
context/spec/
  architecture.md
  composition.md
  features.md
  http-openapi.md
  admin.md
  admin-uikit.md
  quality-release.md
  kernel/
  capabilities/
```
