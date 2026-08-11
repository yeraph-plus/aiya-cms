# Comments Capability 规格

## 1. 职责与边界

comments 独立维护面向业务目标的评论、层级回复和审核状态，不属于 content 内部模型。它只保存 opaque `target_type` / `target_id` 与 `author_type` / `author_id`，不导入兄弟 capability、不建立跨能力外键或 ORM relationship；目标有效性由组合根提供的 `TargetExistsPort` 校验。

评论正文由本能力持久化。首版只接受纯文本，前端不得把正文当作 HTML 渲染。父评论只能来自同一 target；最多允许一层回复，避免把无限层级树隐式塞进列表接口。

## 2. 表与状态机

`comments` 归属 `capability:comments`，至少包含：

- `target_type`、`target_id`；
- `author_type`、`author_id`；
- 可空的内部 `parent_id` 自外键；
- `body`；
- `status`：`pending`、`published`、`rejected`、`deleted`；
- `moderation_reason` 与 submitted/published/rejected/deleted 时间；
- 乐观并发 `version` 和统一 created/updated 时间。

合法转换为 `pending -> published|rejected|deleted`、`published -> rejected|deleted`、`rejected -> published|deleted`。`deleted` 是终态软删除；读接口不返回已删除正文。重复执行目标状态相同的审核命令幂等返回当前记录。

## 3. Commands 与 Query

- `SubmitComment`：校验目标、父评论和纯文本正文，创建 `pending` 评论。
- `ApproveComment`：审核为 `published`。
- `RejectComment`：要求非空原因并审核为 `rejected`。
- `DeleteComment`：软删除并记录可选原因。
- `ListPublishedComments`：用户侧只读 `published` 评论，按 `submitted_at,id` 升序稳定分页。
- `ListAdminComments`：按 status、target、author 过滤，按 `submitted_at,id` 倒序稳定分页。
- `GetAdminComment`：返回单条审核记录。

Command 只写 comments 自有表与同事务 outbox；Query 不写库、不发事件。业务写入不导出万能 PATCH/CRUD。

## 4. 事件、审计与权限

事件使用稳定 key：`comments.submitted.v1`、`comments.approved.v1`、`comments.rejected.v1`、`comments.deleted.v1`。所有审核写入同时追加 `audit.entry.recorded.v1`，记录 actor、target 和原因，不复制评论全文。

权限 key：

- `comments.read`：管理侧列表和详情；
- `comments.submit`：保留给策略与授权清单；HTTP 用户提交以已认证主体为边界；
- `comments.moderate`：通过、拒绝；
- `comments.delete`：软删除。

## 5. HTTP

用户侧通用端点：

- `GET /api/v1/content/{target_type}/{target_id}/comments`；
- `POST /api/v1/content/{target_type}/{target_id}/comments`（需要登录）。

管理侧只导出 `/api/v1/admin/**`：

- `GET /api/v1/admin/comments`；
- `GET /api/v1/admin/comments/{comment_id}`；
- `POST /api/v1/admin/comments/{comment_id}/approve`；
- `POST /api/v1/admin/comments/{comment_id}/reject`；
- `POST /api/v1/admin/comments/{comment_id}/delete`。

管理 SPA 使用列表工作台、详情抽屉和敏感操作模态框，不注册评论详情页。

## 6. 验收

覆盖目标缺失、跨 target 父评论、超过一层回复、非法状态转换、重复审核幂等、软删除正文隐藏、权限、事件/审计同事务、确定性分页、公开端点只泄露 published 状态，以及未装配 comments 时路由为 404。
