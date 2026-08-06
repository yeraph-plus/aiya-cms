# Kernel / 总览（00-kernel-overview）

## 1. 设计目的

内核层是全系统的稳定底座：① 引入并封装基础设施（PG、APScheduler、SMTP、Redis、日志）；② 实现核心逻辑（身份、认证、RBAC、审计、设置、事件、Pipeline、任务）；③ 提供 CMS 通用对象模型（Content、Taxonomy、Comment）。内核初版完成后**封装暴露、轻易不变动**——所有模块只依赖本页列出的公开 API。

非目标：内核不提供 `post`、`forum`、`issue` 等具体内容类型，不知道具体站点字段和业务流程；积分、通知、支付、搜索等扩展仍属于 modules。CMS 对象归属调整见 ADR-0032。

## 2. 组件清单与内部依赖顺序

依赖方向自上而下（上层可用下层，禁止反向）：

| 序 | 组件 | 规格 | 一句话 |
|---|---|---|---|
| 1 | config | [config.md](config.md) | pydantic-settings 集中配置 |
| 2 | errors | [errors.md](errors.md) | AppError 体系 + 错误码注册表 |
| 3 | logging | [logging.md](logging.md) | 结构化日志初始化 |
| 4 | db | [db-uow-repository.md](db-uow-repository.md) | engine/Base/mixins/JsonBModel/UoW/Repository |
| 5 | cache | [cache.md](cache.md) | Cache Protocol + Redis/Memory 实现 |
| 6 | security | [security.md](security.md) | 密码哈希、JWT、Principal |
| 7 | identity | [identity.md](identity.md) | Identity/User/Organization 占位 |
| 8 | rbac | [rbac.md](rbac.md) | Role/Permission/Policy |
| 9 | events | [events.md](events.md) | Event 基类 + EventBus |
| 10 | auth | [auth.md](auth.md) | 注册/登录/双令牌/吊销（发事件故在 events 之后） |
| 11 | pipeline | [pipeline.md](pipeline.md) | 注册表 + StepContext + 执行器 |
| 12 | tasks | [tasks.md](tasks.md) | 调度器壳 + BaseTask + Cron + LISTEN/NOTIFY |
| 13 | mail | [mail.md](mail.md) | SMTP 封装 + outbox + Cron 重投 |
| 14 | audit | [audit.md](audit.md) | audit_logs + 异步写入 |
| 15 | settings | [settings.md](settings.md) | settings 表 + 类型化读取 + 缓存 |
| 16 | content | 待由 G0 新建 `content.md` | Content 基实现 + 声明解释器 + 类型注册表 |
| 17 | taxonomy | 待由 G0 新建 `taxonomy.md` | Term/Relationship + type/group 隔离 + 组合筛选 |
| 18 | comment | 待由 G0 新建 `comment.md` | 多态目标 + 评论树 + 审核/限频 |

## 3. 公开 API 清单（稳定承诺）

模块/api 只允许使用以下入口（各组件 `__init__.py` 显式导出，未导出即私有）：

| 组件 | 公开符号 |
|---|---|
| config | `Settings`, `get_settings` |
| errors | `AppError`, `ErrorCode`, `register_error_codes`, `validate_registry`, `app_error_handler`, `unhandled_exception_handler`, `request_validation_handler` |
| logging | `get_logger` |
| db | `Base`, `TimestampMixin`, `JsonBModel`, `AbstractUnitOfWork`, `Repository[ModelT]`, `Page[T]` |
| cache | `Cache` (Protocol), `build_cache` |
| security | `Principal`, `hash_password`, `verify_password`, `TokenService` |
| identity | `UserRead`, `IdentityService`（查用户要素） |
| rbac | `CapabilityChecker`, `require_capability`（FastAPI 依赖） |
| auth | `AuthService`, `get_current_principal`（FastAPI 依赖） |
| events | `Event`, `EventBus`, `subscribe`（经 wiring） |
| pipeline | `PipelineKey`, `StepContext`, `PipelineRegistry`, `PipelineExecutor` |
| tasks | `BaseTask`, `TaskScheduler`, `TaskState` |
| mail | `MailService`（enqueue 语义） |
| audit | `AuditService.record` |
| settings | `SettingGroup` / `SettingField` declarations + `SettingsService` interpreter |
| content | `ContentType`, `ContentField`, status/transition/group/comment/trash definitions, `ContentTypeRegistry`, `ContentService` |
| taxonomy | `TermService`, taxonomy DTO/query contracts |
| comment | `CommentService`, `TargetExists`, comment DTO/query contracts |

稳定承诺：ADR-0032 的 M2.1 重写完成前仍处于 0.1.0 破坏性设计窗口，不保留旧 modules 路径兼容；完成并封板后，上述公开符号与基础表才进入向后兼容承诺。任何后续破坏性变更必须 ADR + 主版本标记。

## 4. 内核基础表清单

`identities` / `users` / `organizations`（占位）/ `roles` / `permissions` / `role_permissions` / `user_roles` / `refresh_tokens` / `audit_logs` / `settings` / `task_instances` / `mail_outbox` / `contents` / `terms` / `term_relationships` / `comments`。表结构详见各组件规格第 5 节。

## 5. 内核级事件清单

`user.registered` / `user.login_succeeded` / `user.login_failed` / `user.password_changed` / `user.banned` / `user.unbanned` / `user.deleted` / `role.assigned` / `setting.updated` / `task.started` / `task.succeeded` / `task.failed` / `task.cancelled` / `mail.send_failed` / `content.created` / `content.updated` / `content.published` / `content.trashed` / `content.restored` / `content.deleted` / `term.created` / `term.updated` / `term.deleted` / `term.assigned` / `comment.created` / `comment.updated` / `comment.deleted` / `comment.moderated`。payload 模型见各组件规格第 8 节。

## 6. 未决事项

- 多实例部署时的 Cron leader 选举（tasks.md 第 12 节）。
- OAuth Provider 实装（identity.md 已预留 provider 维度）。
