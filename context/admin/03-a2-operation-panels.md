# Admin / A2 操作面板与管理闭环

> M2.1 G0 更新：Content/Taxonomy/Comment 基实现迁入 kernel；管理端只消费 kernel OpenAPI，不再依赖 modules 内部 DTO。目标类型由 post/forum/issue 声明并由 `/content-types` 返回。

> 状态：实施中（2026-08-05）。本规格覆盖管理员端七个导航面板、真实数据首页和只读账户概览；不覆盖公开站点前台、媒体库、修订历史或 M3 模块。

## 1. 交付边界

- 用户、内容、分类、评论、审计、设置、任务七个面板均使用真实 FastAPI 契约，不再显示占位结果。
- 首页显示按 Capability 裁剪的用户、内容、待审评论、活动任务统计，并保留健康检查。
- 账户页只读展示 `/auth/me` 的资料、角色和 Capability；个人资料保存、通知设置和改密码待后续规格。
- 列表筛选、分页、排序写入 URL query；详情和编辑使用独立子路由；0.1.0 不提供批量写操作。

## 2. 后端契约

### 2.1 管理资源

| 资源 | 只读 | 写入 | Capability |
|---|---|---|---|
| users | 列表、详情、角色与权限 | 资料、角色替换、封禁/解封 | `user:read_any`、`user:update_any`、`role:assign`、`user:ban` |
| content | 类型元数据、列表、详情 | 创建、编辑、发布/下架、归档/恢复、回收站/清除 | 现有 `content:*` |
| taxonomy | 类型/分组、term 列表、详情 | term CRUD、内容关联 | `term:manage`、`term:assign` |
| comments | 全局审核队列、详情 | 审核、垃圾标记、删除 | `comment:moderate`、`comment:delete_any` |
| audit | 分页、详情 | 无 | `audit:read` |
| settings | 登记组、字段元数据、当前值、默认值、Schema | PATCH 用户覆盖值或恢复默认 | `setting:read`、`setting:update` |
| tasks | 分页、详情 | 0.1.0 无 | `task:manage` |

### 2.2 新增 DTO 与路径

- `UserAdminRead`、`UserAdminUpdate`、`UserRoleSet`、`UserQuery`；用户名和邮箱只读，角色为内置 seed 角色的多选集合。
- `ContentTypeRead` 暴露 `type_name`、标题描述、状态/动作转换、字段元数据、taxonomy groups、comment policy 和 query allow-list；post/forum/issue 均由注册表返回，前端不得硬编码类型或字段。
- `CommentModerationQuery`、`SettingGroupRead`、`TaskQuery`、`DashboardSummary`。
- 新增 `GET /api/v1/users`、`PATCH /api/v1/users/{id}`、`PUT /api/v1/users/{id}/roles`、`GET /api/v1/content-types`、`GET /api/v1/terms/{type_name}`、`GET /api/v1/terms/{type_name}/{id}`、`GET /api/v1/comments/moderation`、`GET /api/v1/comments/moderation/{id}`、`GET /api/v1/audit-logs/{id}`、`GET /api/v1/settings`、`PATCH /api/v1/settings/{group_slug}`、`GET /api/v1/tasks`、`GET /api/v1/tasks/{id}`、`GET /api/v1/dashboard`。
- 内容动作由当前 type 的 transition 元数据渲染；关键词/状态/排序方向遵循 ADR-0030。`trash`/`restore` 使用 kernel 通用语义，`purge` 仅在允许时展示；不保留旧动作兼容路径。

### 2.3 安全与登记

- 后端 Capability 是最终授权；前端只控制可见性和按钮状态。
- 禁止当前管理员封禁自己或替换自己的角色，保证最后一个可操作管理员不会被界面锁死。
- 注册 `role.membership_replaced` 事件和对应审计；新增错误码先登记后使用。
- 服务层仍只接收/返回 DTO，不接收 Session；Dashboard 只通过 Service/Repository 查询 DTO，不写业务数据。

## 3. 前端交互

- 列表页使用 URL query 保存筛选、分页、关键词和排序，默认每页 20、最大 100；四类列表契约见 ADR-0030，taxonomy 返回分页对象。
- 详情和编辑使用独立子路由：`users/:id`、`content/:type/new`、`content/:type/:slug`、`taxonomy/:type/new`、`taxonomy/:type/:id`、`comments/:id`、`audit/:id`、`tasks/:id`。
- 所有写操作显式保存、服务端成功后刷新；敏感动作逐项确认，永久删除二次确认，不提供批量写。
- Markdown 使用编辑/安全预览双栏；ContentField 的 input_type/constraints 生成表单，持久化值统一为字符串；复杂字段若未登记则不提供 JSON 回退。
- 用户、分类、评论、设置、审计、任务面板分别具备 loading、empty、error、403 和移动端状态。
- 内容和分类导航使用 any-of Capability；动作按钮按具体 Capability 隐藏，后端拒绝时显示稳定错误码与 request_id。

## 4. OpenAPI 冻结

- 冻结产物为仓库根 `openapi.json` 与 `openapi.sha256`。
- `python -m inc.api.openapi dump/check` 负责生成与校验；管理员 `generate:api/check:api` 从根快照生成只读 TypeScript 类型。
- 后端测试必须检测快照漂移；契约变更必须先更新规格、再 dump、再生成客户端和消费方。

## 5. 验收

- 后端 pytest 覆盖分页/筛选、Capability 403、角色替换与自身保护、完整内容状态机、Schema 元数据、评论审核队列、任务/审计详情、设置发现、Dashboard 按权限裁剪和 OpenAPI 漂移。
- 管理员 Vitest 覆盖查询序列化、Capability 可见性、Schema 表单与 JSON 回退、Markdown 清洗、状态动作矩阵和错误展示。
- Mock/Real Playwright 覆盖桌面与移动视口；真实链路创建唯一用户、term、Markdown 内容和评论，验证角色、发布、审核、设置恢复、审计查询和任务空态/详情。
